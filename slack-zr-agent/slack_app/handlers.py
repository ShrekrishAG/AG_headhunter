from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from pathlib import Path

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from slack_app.messages import (
    APPROVE_LOGIN_ACTION,
    APPROVE_UNLOCK_ACTION,
    DECLINE_LOGIN_ACTION,
    DECLINE_UNLOCK_ACTION,
    EXPORT_AFTER_UNLOCK_ACTION,
    EXPORT_CANDIDATES_ACTION,
    EXPORT_MODAL_CALLBACK,
    REFRESH_PROJECTS_ACTION,
    REVIEW_CANDIDATES_ACTION,
    REVIEW_MODAL_CALLBACK,
    SKIP_EXPORT_AFTER_UNLOCK_ACTION,
    export_after_unlock_blocks,
    export_candidates_modal,
    permission_request_blocks,
    refresh_projects_blocks,
    review_candidates_modal,
    unlock_confirmation_blocks,
)
from zr.browser import ZipRecruiterSessionError
from zr.config import (
    ALLOWED_SLACK_USER_ID,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
    SLACK_NOTIFY_USER_ID,
    SLACK_SIGNING_SECRET,
)
from zr.export import export_all_candidates, format_export_for_slack
from zr.export_options import ExportOptions, parse_export_options, parse_slack_modal_values
from zr.headhunter_pipeline import format_pipeline_slack_message, run_post_export_pipeline
from zr.pipeline_review import (
    PipelineReviewResult,
    format_review_for_slack,
    run_pipeline_review,
    unlock_review_top,
)
from zr.projects import fetch_projects, format_projects_for_slack
from zr.review_options import (
    ReviewOptions,
    parse_review_options,
    parse_slack_review_modal_values,
)
from zr.review_sessions import create_session, drop_session, get_session, update_session

logger = logging.getLogger(__name__)

app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)


def _slack_block_text(text: str, *, limit: int = 2900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _review_block_summary(message: str, unlock_count: int) -> str:
    first_lines = message.splitlines()[:6]
    summary = "\n".join(first_lines).strip()
    if not summary:
        summary = f"Review complete. Unlock {unlock_count} candidate(s)?"
    summary = _slack_block_text(summary, limit=900)
    return f"{summary}\n\nUnlock *{unlock_count}* candidate(s)?"


def _is_authorized(user_id: str | None) -> bool:
    if not ALLOWED_SLACK_USER_ID:
        return True
    return user_id == ALLOWED_SLACK_USER_ID


def _build_export_zip(result) -> Path:
    zip_path = result.export_dir / "candidates_export.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(result.csv_path, arcname="candidates.csv")
        for resume_path in sorted(result.resumes_dir.glob("*.pdf")):
            archive.write(resume_path, arcname=f"resumes/{resume_path.name}")
    return zip_path


async def _upload_export_files(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str | None,
    result,
) -> None:
    zip_path = _build_export_zip(result)
    await client.files_upload_v2(
        channel=channel,
        thread_ts=thread_ts,
        file=str(zip_path),
        title="candidates_export.zip",
        initial_comment=(
            f"Export bundle: CSV + {result.resume_count} resume PDF(s). "
            "Unzip to get the `resumes/` folder."
        ),
    )


async def _run_pipeline_review_flow(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str | None,
    options: ReviewOptions,
) -> None:
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            "Reviewing locked pipeline candidates on ZipRecruiter. "
            f"{options.summary_line()}\n"
            "This may take a few minutes (browser + AI scoring)..."
        ),
    )

    try:
        result = await run_pipeline_review(options)
        message = format_review_for_slack(result)
        session = create_session(
            channel=channel,
            thread_ts=thread_ts,
            result=result,
        )
        response = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": _review_block_summary(
                            message, result.total_unlock_count
                        ),
                    },
                },
                *unlock_confirmation_blocks(
                    session.session_id, result.total_unlock_count
                ),
            ],
        )
        session.thread_ts = thread_ts or response.get("ts")
    except ZipRecruiterSessionError as error:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"ZipRecruiter pipeline review error:\n```{error}```\n"
                "Try: `python login.py` then run `/zr-review` again."
            ),
        )
    except Exception as error:
        logger.exception("Pipeline review failed")
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unexpected error during pipeline review:\n```{error}```",
        )


async def _run_unlock_for_session(
    client: AsyncWebClient,
    session_id: str,
) -> None:
    session = get_session(session_id)
    if not session:
        logger.warning("Unlock session not found: %s", session_id)
        return

    channel = session.channel
    thread_ts = session.thread_ts
    targets = session.top_to_unlock()
    if not targets:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No candidates selected to unlock.",
        )
        drop_session(session_id)
        return

    credit_count = session.total_unlock_count
    project_summary = ", ".join(
        f"{slice_.project.name} ({len(slice_.top_candidates)})"
        for slice_ in session.slices
        if slice_.top_candidates
    )
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f"Unlocking *{credit_count}* candidate(s) across "
            f"{len(session.slices)} project(s) ({credit_count} credit(s))...\n"
            f"• {project_summary}"
        ),
    )

    try:
        result = PipelineReviewResult(slices=list(session.slices))
        unlocked_by_project = await unlock_review_top(result)
        unlocked_total = sum(len(items) for items in unlocked_by_project.values())
        detail_lines = []
        for project_name, unlocked in unlocked_by_project.items():
            names = ", ".join(candidate.name for candidate in unlocked) or "none"
            detail_lines.append(f"• *{project_name}*: {names}")
        if thread_ts:
            session.thread_ts = thread_ts
        update_session(session)
        sync_dashboard = session.sync_dashboard()
        export_prompt = (
            "Export CSV + resumes and run the post-export pipeline?"
            if sync_dashboard
            else "Export CSV + resumes? (VP sourcing — no dashboard sync)"
        )
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"Unlocked *{unlocked_total}* candidate(s) "
                f"({unlocked_total} credit(s) spent).\n"
                + "\n".join(detail_lines)
                + f"\n\n{export_prompt}"
            ),
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"Unlocked *{unlocked_total}* candidate(s). {export_prompt}"
                        ),
                    },
                },
                *export_after_unlock_blocks(
                    session_id, sync_dashboard=sync_dashboard
                ),
            ],
        )
    except ZipRecruiterSessionError as error:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unlock failed:\n```{error}```",
        )
        drop_session(session_id)
    except Exception as error:
        logger.exception("Unlock flow failed")
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unexpected error during unlock:\n```{error}```",
        )
        drop_session(session_id)


async def _run_export_after_unlock(
    client: AsyncWebClient,
    session_id: str,
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> None:
    session = get_session(session_id)
    if not session:
        logger.warning("Export session not found: %s", session_id)
        if channel:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    "I could not find the review session for that export button. "
                    "The bot may have restarted after unlock.\n\n"
                    "Run `/zr-export` and set per-project limits, e.g.:\n"
                    "`TGC - St Louis=10`\n"
                    "`TGC - KC, MO=10`"
                ),
            )
        return

    target_channel = channel or session.channel
    target_thread = thread_ts or session.thread_ts
    project_limits = session.export_project_limits()
    if not project_limits:
        await client.chat_postMessage(
            channel=target_channel,
            thread_ts=target_thread,
            text="No candidates were queued for export from that review session.",
        )
        drop_session(session_id)
        return

    options = ExportOptions(
        default_per_project_limit=None,
        project_limits=project_limits,
    )

    drop_session(session_id)
    logger.info(
        "Starting post-unlock export for session %s with limits %s",
        session_id,
        project_limits,
    )
    await _run_candidate_export(
        client,
        target_channel,
        thread_ts=target_thread,
        options=options,
        sync_dashboard=session.sync_dashboard(),
    )


async def _run_candidate_export(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str | None = None,
    options: ExportOptions | None = None,
    *,
    sync_dashboard: bool = True,
) -> None:
    export_options = options or ExportOptions()
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            "Exporting unlocked candidates from ZipRecruiter. "
            f"{export_options.summary_line()}\n"
            "This may take a few minutes..."
        ),
    )

    try:
        result = await export_all_candidates(export_options)
        message = format_export_for_slack(result)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                *refresh_projects_blocks(),
            ],
        )

        if result.csv_path.exists():
            try:
                await _upload_export_files(client, channel, thread_ts, result)
            except Exception as upload_error:
                logger.warning("Slack export upload failed: %s", upload_error)
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=(
                        "Export finished, but I could not upload files to Slack.\n"
                        "Add the *files:write* bot scope in your Slack app settings, "
                        "reinstall the app, then try again.\n\n"
                        f"Your CSV and {result.resume_count} resume PDF(s) are saved locally at:\n"
                        f"• `{result.csv_path}`\n"
                        f"• `{result.resumes_dir}`"
                    ),
                )

        if sync_dashboard:
            pipeline_summary = await asyncio.to_thread(
                run_post_export_pipeline, result.export_dir
            )
            pipeline_message = format_pipeline_slack_message(
                pipeline_summary, export_dir=result.export_dir
            )
            if pipeline_message:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=pipeline_message,
                )
        else:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    "Export complete — CSV + resumes uploaded. "
                    "Skipped dashboard sync (sourcing-only role)."
                ),
            )
    except ZipRecruiterSessionError as error:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"ZipRecruiter export error:\n```{error}```\n"
                "Try: `python login.py` then click *Export candidates* again."
            ),
        )
    except Exception as error:
        logger.exception("Candidate export failed")
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unexpected error during export:\n```{error}```",
        )


async def _run_project_fetch(client: AsyncWebClient, channel: str, thread_ts: str | None = None) -> None:
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Fetching unlocked candidate counts from ZipRecruiter...",
    )

    try:
        result = await fetch_projects()
        message = format_projects_for_slack(result)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                *refresh_projects_blocks(),
            ],
        )
    except ZipRecruiterSessionError as error:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"ZipRecruiter error:\n```{error}```\n"
                "Try: `python login.py` then click *Refresh project list*."
            ),
        )
    except Exception as error:
        logger.exception("Project fetch failed")
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message.lower():
            hint = (
                "Browser not installed for Playwright. In terminal run:\n"
                "`playwright install chromium`\n"
                "Then restart: `python main.py`"
            )
        else:
            hint = message
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unexpected error while fetching projects:\n```{hint}```",
        )


async def open_dm_channel(client: AsyncWebClient, user_id: str) -> str:
    response = await client.conversations_open(users=user_id)
    return response["channel"]["id"]


async def _send_permission_request_to_channel(client: AsyncWebClient, channel: str) -> None:
    await client.chat_postMessage(
        channel=channel,
        text="Can I log into ZipRecruiter and list your Resume Database projects?",
        blocks=permission_request_blocks(),
    )


async def send_permission_request(client: AsyncWebClient, user_id: str | None = None) -> None:
    target_user = user_id or SLACK_NOTIFY_USER_ID
    channel = await open_dm_channel(client, target_user)
    await _send_permission_request_to_channel(client, channel)


async def _handle_zr_projects_command(ack, command, client):
    await ack()

    user_id = command.get("user_id")
    channel_id = command["channel_id"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="You are not authorized to run the ZipRecruiter agent.",
        )
        return

    await _run_project_fetch(client, channel_id)


def _wants_pipeline_review(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "zr-review",
            "pipeline review",
            "review pipeline",
            "review top",
            "unlock top",
            "qualify top",
            "score top",
            "review locked",
        )
    )


def _wants_candidate_export(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "export candidates",
            "export candidate",
            "download resumes",
            "download resume",
            "export csv",
            "export resumes",
        )
    )


def _wants_project_list(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "project",
            "projects",
            "list",
            "counts",
            "unlocked",
            "ziprecruiter",
            "zip recruiter",
            "resume database",
        )
    )


@app.event("message")
async def handle_direct_message(event, client, logger):
    if event.get("bot_id") or event.get("subtype"):
        return

    if event.get("channel_type") != "im":
        return

    user_id = event.get("user")
    if not user_id:
        return

    text = event.get("text") or ""
    if _wants_pipeline_review(text):
        if not _is_authorized(user_id):
            await client.chat_postMessage(
                channel=event["channel"],
                text="You are not authorized to use the ZipRecruiter agent.",
            )
            return

        logger.info("DM pipeline review request from user %s", user_id)
        options = parse_review_options(text)
        await _run_pipeline_review_flow(client, event["channel"], None, options=options)
        return

    if _wants_candidate_export(text):
        if not _is_authorized(user_id):
            await client.chat_postMessage(
                channel=event["channel"],
                text="You are not authorized to use the ZipRecruiter agent.",
            )
            return

        logger.info("DM export request from user %s", user_id)
        options = parse_export_options(text)
        await _run_candidate_export(client, event["channel"], options=options)
        return

    if not _wants_project_list(text):
        return

    if not _is_authorized(user_id):
        await client.chat_postMessage(
            channel=event["channel"],
            text="You are not authorized to use the ZipRecruiter agent.",
        )
        return

    logger.info("DM project request from user %s", user_id)
    await _run_project_fetch(client, event["channel"])


@app.command("/zr-review")
async def handle_zr_review(ack, command, client):
    await ack()

    user_id = command.get("user_id")
    channel_id = command["channel_id"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="You are not authorized to run the ZipRecruiter agent.",
        )
        return

    command_text = (command.get("text") or "").strip()
    if not command_text:
        metadata = json.dumps({"channel": channel_id, "thread_ts": None})
        modal = review_candidates_modal()
        modal["private_metadata"] = metadata
        await client.views_open(
            trigger_id=command["trigger_id"],
            view=modal,
        )
        return

    await _run_pipeline_review_flow(
        client,
        channel_id,
        None,
        options=parse_review_options(command_text),
    )


@app.command("/zr-export")
async def handle_zr_export(ack, command, client):
    await ack()

    user_id = command.get("user_id")
    channel_id = command["channel_id"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="You are not authorized to run the ZipRecruiter agent.",
        )
        return

    await _run_candidate_export(
        client,
        channel_id,
        options=parse_export_options(command.get("text") or ""),
    )


@app.command("/zr-projects")
async def handle_zr_projects(ack, command, client):
    await _handle_zr_projects_command(ack, command, client)


@app.command("/zr-project")
async def handle_zr_project_alias(ack, command, client):
    await _handle_zr_projects_command(ack, command, client)


@app.action(APPROVE_LOGIN_ACTION)
async def handle_approve_login(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to approve ZipRecruiter login.",
        )
        return

    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text="Approved. Starting ZipRecruiter login...",
    )

    asyncio.create_task(_run_project_fetch(client, channel, thread_ts=message_ts))


@app.action(DECLINE_LOGIN_ACTION)
async def handle_decline_login(ack, body, client):
    await ack()

    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text="Skipped. Ask again anytime with `/zr-projects`.",
    )


@app.action(REFRESH_PROJECTS_ACTION)
async def handle_refresh_projects(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]
    message_ts = body.get("message", {}).get("ts")

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to refresh ZipRecruiter projects.",
        )
        return

    asyncio.create_task(_run_project_fetch(client, channel, thread_ts=message_ts))


@app.action(APPROVE_UNLOCK_ACTION)
async def handle_approve_unlock(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]
    message_ts = body.get("message", {}).get("ts")
    session_id = body.get("actions", [{}])[0].get("value", "")

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to unlock ZipRecruiter candidates.",
        )
        return

    if not session_id:
        return

    asyncio.create_task(_run_unlock_for_session(client, session_id))


@app.action(DECLINE_UNLOCK_ACTION)
async def handle_decline_unlock(ack, body, client):
    await ack()

    channel = body["channel"]["id"]
    message_ts = body.get("message", {}).get("ts")
    session_id = body.get("actions", [{}])[0].get("value", "")
    drop_session(session_id)
    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text="Skipped unlock. No credits spent.",
    )


@app.action(EXPORT_AFTER_UNLOCK_ACTION)
async def handle_export_after_unlock(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]
    session_id = body.get("actions", [{}])[0].get("value", "")

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to export ZipRecruiter candidates.",
        )
        return

    if not session_id:
        return

    message_ts = body.get("message", {}).get("ts")
    session = get_session(session_id)
    if session:
        if not session.thread_ts:
            session.thread_ts = message_ts
        update_session(session)

    asyncio.create_task(
        _run_export_after_unlock(
            client,
            session_id,
            channel=channel,
            thread_ts=message_ts,
        )
    )


@app.action(SKIP_EXPORT_AFTER_UNLOCK_ACTION)
async def handle_skip_export_after_unlock(ack, body, client):
    await ack()

    channel = body["channel"]["id"]
    message_ts = body.get("message", {}).get("ts")
    session_id = body.get("actions", [{}])[0].get("value", "")
    drop_session(session_id)
    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text="Skipped export. Unlocked candidates remain in ZipRecruiter.",
    )


@app.action(EXPORT_CANDIDATES_ACTION)
async def handle_export_candidates(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to export ZipRecruiter candidates.",
        )
        return

    channel = body["channel"]["id"]
    thread_ts = body.get("message", {}).get("ts")
    metadata = json.dumps({"channel": channel, "thread_ts": thread_ts})

    modal = export_candidates_modal()
    modal["private_metadata"] = metadata

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=modal,
    )


@app.view(EXPORT_MODAL_CALLBACK)
async def handle_export_modal_submission(ack, body, client, view):
    await ack()

    user_id = body.get("user", {}).get("id")
    if not _is_authorized(user_id):
        return

    options = parse_slack_modal_values(view.get("state", {}).get("values", {}))

    metadata_raw = body.get("view", {}).get("private_metadata") or "{}"
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        metadata = {}

    channel = metadata.get("channel")
    thread_ts = metadata.get("thread_ts")
    if not channel:
        channel = await open_dm_channel(client, user_id)

    asyncio.create_task(
        _run_candidate_export(client, channel, thread_ts=thread_ts, options=options)
    )


@app.action(REVIEW_CANDIDATES_ACTION)
async def handle_review_candidates(ack, body, client):
    await ack()

    user_id = body.get("user", {}).get("id")
    channel = body["channel"]["id"]

    if not _is_authorized(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="You are not authorized to review ZipRecruiter candidates.",
        )
        return

    thread_ts = body.get("message", {}).get("ts")
    metadata = json.dumps({"channel": channel, "thread_ts": thread_ts})

    modal = review_candidates_modal()
    modal["private_metadata"] = metadata

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=modal,
    )


@app.view(REVIEW_MODAL_CALLBACK)
async def handle_review_modal_submission(ack, body, client, view):
    await ack()

    user_id = body.get("user", {}).get("id")
    if not _is_authorized(user_id):
        return

    options = parse_slack_review_modal_values(view.get("state", {}).get("values", {}))

    metadata_raw = body.get("view", {}).get("private_metadata") or "{}"
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        metadata = {}

    channel = metadata.get("channel")
    thread_ts = metadata.get("thread_ts")
    if not channel:
        channel = await open_dm_channel(client, user_id)

    asyncio.create_task(
        _run_pipeline_review_flow(
            client, channel, thread_ts=thread_ts, options=options
        )
    )


@app.event("app_mention")
async def handle_app_mention(event, client, say):
    user_id = event.get("user")
    if not _is_authorized(user_id):
        await say("You are not authorized to use the ZipRecruiter agent.")
        return

    text = (event.get("text") or "").lower()
    if _wants_pipeline_review(text):
        await _run_pipeline_review_flow(
            client,
            event["channel"],
            None,
            options=parse_review_options(event.get("text") or ""),
        )
    elif _wants_candidate_export(text):
        await _run_candidate_export(
            client,
            event["channel"],
            options=parse_export_options(event.get("text") or ""),
        )
    elif _wants_project_list(text):
        await _run_project_fetch(client, event["channel"])
    else:
        await say(
            "Hi. Type *list my projects*, *export 5 candidates per project*, "
            "*review top 10 per project*, or use `/zr-projects`, `/zr-export`, `/zr-review`."
        )


async def start_socket_mode() -> None:
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required.")

    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()
