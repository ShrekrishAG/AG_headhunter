"""Slack Block Kit payloads for ZipRecruiter agent actions."""

from __future__ import annotations

from zr.projects import Project
from zr.review_options import project_option_value
from zr.role_config import default_role_slug, slack_role_options

APPROVE_LOGIN_ACTION = "zr_approve_login"
DECLINE_LOGIN_ACTION = "zr_decline_login"
REFRESH_PROJECTS_ACTION = "zr_refresh_projects"
EXPORT_CANDIDATES_ACTION = "zr_export_candidates"
EXPORT_MODAL_CALLBACK = "zr_export_modal"
REVIEW_CANDIDATES_ACTION = "zr_review_candidates"
REVIEW_MODAL_CALLBACK = "zr_review_modal"
APPROVE_UNLOCK_ACTION = "zr_approve_unlock"
DECLINE_UNLOCK_ACTION = "zr_decline_unlock"
EXPORT_REVIEW_LIST_ACTION = "zr_export_review_list"
EXPORT_AFTER_UNLOCK_ACTION = "zr_export_after_unlock"
SKIP_EXPORT_AFTER_UNLOCK_ACTION = "zr_skip_export_after_unlock"

# Slack multi_static_select allows at most 100 options; option text/value ≤ 75 chars
_MAX_PROJECT_OPTIONS = 100
_MAX_OPTION_CHARS = 75


def _truncate_slack_text(text: str, limit: int = _MAX_OPTION_CHARS) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def slack_project_option_value(project: Project) -> str:
    """Stable option value: prefer ZR project id, else hashed name key."""
    return project_option_value(project)


def _project_select_options(projects: list[Project]) -> list[dict]:
    options: list[dict] = []
    seen: set[str] = set()
    for project in projects:
        if not (project.project_id or project.name.strip()):
            continue
        value = slack_project_option_value(project)
        if value in seen:
            continue
        seen.add(value)
        options.append(
            {
                "text": {
                    "type": "plain_text",
                    "text": _truncate_slack_text(project.name),
                },
                "value": value,
            }
        )
        if len(options) >= _MAX_PROJECT_OPTIONS:
            break
    return options


def export_candidates_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": EXPORT_MODAL_CALLBACK,
        "title": {"type": "plain_text", "text": "Export candidates"},
        "submit": {"type": "plain_text", "text": "Start export"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Choose how many unlocked candidates to export *per project*. "
                        "Leave the default empty to export all."
                    ),
                },
            },
            {
                "type": "input",
                "block_id": "default_limit_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "default_limit",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. 5 (applies to every project)",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Default limit per project",
                },
            },
            {
                "type": "input",
                "block_id": "project_overrides_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "project_overrides",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "TGC - KC, MO=60\nTGC - Wichita, KS=20\nTGC - madison WI=10",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Per-project overrides (optional)",
                },
                "hint": {
                    "type": "plain_text",
                    "text": "One per line: Project Name=number",
                },
            },
        ],
    }


def review_candidates_modal(
    projects: list[Project] | None = None,
    *,
    projects_error: str | None = None,
) -> dict:
    """
    Review modal.

    Open immediately with ``projects=None`` (loading state), then
    ``views.update`` once active ZR projects are fetched.
    """
    role_options = slack_role_options()
    initial_role = default_role_slug()
    initial_option = next(
        (opt for opt in role_options if opt["value"] == initial_role),
        role_options[0] if role_options else None,
    )

    blocks: list[dict] = [
        {
            "type": "input",
            "block_id": "role_block",
            "element": {
                "type": "static_select",
                "action_id": "role_slug",
                "options": role_options,
                **(
                    {"initial_option": initial_option}
                    if initial_option is not None
                    else {}
                ),
            },
            "label": {"type": "plain_text", "text": "Position"},
            "hint": {
                "type": "plain_text",
                "text": "Rubric used when AI scores locked candidates",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Pick which *active ZipRecruiter projects* to review, then set "
                    "how many locked profiles to score and unlock per project."
                ),
            },
        },
    ]

    if projects_error:
        blocks.append(
            {
                "type": "section",
                "block_id": "projects_status_block",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":warning: Could not load projects:\n```{projects_error[:400]}```\n"
                        "Cancel and try `/zr-review` again after `/zr-projects` works."
                    ),
                },
            }
        )
    elif projects is None:
        blocks.append(
            {
                "type": "section",
                "block_id": "projects_status_block",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":hourglass_flowing_sand: Loading active ZipRecruiter projects… "
                        "Wait until the list appears before submitting."
                    ),
                },
            }
        )
    else:
        project_options = _project_select_options(projects)
        if not project_options:
            blocks.append(
                {
                    "type": "section",
                    "block_id": "projects_status_block",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            ":warning: No active projects found. "
                            "Cancel and check ZipRecruiter / run `/zr-projects`."
                        ),
                    },
                }
            )
        else:
            hint = "Select one or more active projects to include in this review."
            if len(projects) > _MAX_PROJECT_OPTIONS:
                hint += f" Showing first {_MAX_PROJECT_OPTIONS} of {len(projects)}."
            blocks.append(
                {
                    "type": "input",
                    "block_id": "projects_block",
                    "element": {
                        "type": "multi_static_select",
                        "action_id": "project_ids",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select projects…",
                        },
                        "options": project_options,
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Projects to review",
                    },
                    "hint": {"type": "plain_text", "text": hint},
                }
            )

    blocks.extend(
        [
            {
                "type": "input",
                "block_id": "default_unlock_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "default_unlock",
                    "initial_value": "5",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. 10 (unlock top 10 per project)",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Unlock top N per project",
                },
            },
            {
                "type": "input",
                "block_id": "default_review_pool_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "default_review_pool",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. 25 (locked profiles to score per project)",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Review pool per project",
                },
                "hint": {
                    "type": "plain_text",
                    "text": "How many locked profiles to score before picking top N. Default 25.",
                },
            },
            {
                "type": "input",
                "block_id": "project_overrides_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "project_overrides",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "TGC St Louis=10\nTGC Seattle=5",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Per-project unlock overrides (optional)",
                },
                "hint": {
                    "type": "plain_text",
                    "text": "One per line: Project Name=number to unlock",
                },
            },
        ]
    )

    return {
        "type": "modal",
        "callback_id": REVIEW_MODAL_CALLBACK,
        "title": {"type": "plain_text", "text": "Review locked pipeline"},
        "submit": {"type": "plain_text", "text": "Start review"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def permission_request_blocks() -> list[dict]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "ZipRecruiter Agent"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Can I log into your ZipRecruiter account and list your "
                    "*Resume Database* projects?"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Yes, login"},
                    "style": "primary",
                    "action_id": APPROVE_LOGIN_ACTION,
                    "value": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not now"},
                    "action_id": DECLINE_LOGIN_ACTION,
                    "value": "decline",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "The agent only runs after you click *Yes, login*.",
                }
            ],
        },
    ]


def unlock_confirmation_blocks(session_id: str, unlock_count: int) -> list[dict]:
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": f"Yes, unlock {unlock_count} ({unlock_count} credits)",
                    },
                    "style": "primary",
                    "action_id": APPROVE_UNLOCK_ACTION,
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Export list (no unlock)",
                    },
                    "action_id": EXPORT_REVIEW_LIST_ACTION,
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "No, skip unlock"},
                    "action_id": DECLINE_UNLOCK_ACTION,
                    "value": session_id,
                },
            ],
        }
    ]


def export_after_unlock_blocks(session_id: str, *, sync_dashboard: bool = True) -> list[dict]:
    export_label = "Export & sync" if sync_dashboard else "Export CSV + resumes"
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": export_label},
                    "style": "primary",
                    "action_id": EXPORT_AFTER_UNLOCK_ACTION,
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip export"},
                    "action_id": SKIP_EXPORT_AFTER_UNLOCK_ACTION,
                    "value": session_id,
                },
            ],
        }
    ]


def refresh_projects_blocks() -> list[dict]:
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Refresh project list"},
                    "action_id": REFRESH_PROJECTS_ACTION,
                    "value": "refresh",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Export candidates (CSV + resumes)"},
                    "style": "primary",
                    "action_id": EXPORT_CANDIDATES_ACTION,
                    "value": "export",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Review locked pipeline"},
                    "action_id": REVIEW_CANDIDATES_ACTION,
                    "value": "review",
                },
            ],
        }
    ]
