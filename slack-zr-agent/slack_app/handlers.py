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
    DECLINE_LOGIN_ACTION,
    EXPORT_CANDIDATES_ACTION,
    EXPORT_MODAL_CALLBACK,
    REFRESH_PROJECTS_ACTION,
    export_candidates_modal,
    permission_request_blocks,
    refresh_projects_blocks,
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
from zr.projects import fetch_projects, format_projects_for_slack

logger = logging.getLogger(__name__)

app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)


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


async def _run_candidate_export(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str | None = None,
    options: ExportOptions | None = None,
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


@app.event("app_mention")
async def handle_app_mention(event, client, say):
    user_id = event.get("user")
    if not _is_authorized(user_id):
        await say("You are not authorized to use the ZipRecruiter agent.")
        return

    text = (event.get("text") or "").lower()
    if _wants_candidate_export(text):
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
            "use `/zr-projects` or `/zr-export 5`."
        )


async def start_socket_mode() -> None:
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required.")

    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()
