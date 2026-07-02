APPROVE_LOGIN_ACTION = "zr_approve_login"
DECLINE_LOGIN_ACTION = "zr_decline_login"
REFRESH_PROJECTS_ACTION = "zr_refresh_projects"
EXPORT_CANDIDATES_ACTION = "zr_export_candidates"
EXPORT_MODAL_CALLBACK = "zr_export_modal"


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
                        "text": "Accord Seattle=10\nAccord NYC=5",
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
            ],
        }
    ]
