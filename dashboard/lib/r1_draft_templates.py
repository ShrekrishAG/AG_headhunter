"""Template-based invite redrafts (no LLM API required)."""

from __future__ import annotations

from lib.constants import ROLE_TITLE
from lib.r1_email_invite import build_r1_email_body, build_r1_email_subject
from lib.r1_invite import build_r1_sms_body, first_name

SMS_TEMPLATES = [
    """Hi {first_name} — Accord Group recruiting. You stood out for our {role} role.

Would you have 30 min for a phone screen with our hiring team next week?

Book here: {calendly_url}

Reply STOP to opt out.""",
    """Hi {first_name}, this is Accord Group. We'd like to invite you to a quick phone screen for our {role} opening.

Pick a time here: {calendly_url}

Reply STOP to opt out.""",
    """{first_name}, thanks for your interest in Accord Group. Your resume looks like a fit for {role}.

Schedule a 30-min call: {calendly_url}

Reply STOP to opt out.""",
]

EMAIL_SUBJECT_TEMPLATES = [
    "Accord Group — Project Sales Representative phone screen",
    "Invitation: Accord Group phone screen — Project Sales Rep",
    "Accord Group recruiting — schedule your phone screen",
]

EMAIL_BODY_TEMPLATES = [
    """Hi {first_name},

Thank you for your interest in the {role} role at Accord Group. We'd like to invite you to a 30-minute phone screen with our hiring team.

Please pick a time that works for you:
{calendly_url}

Best,
Accord Group Recruiting

---
Accord Group · Lee's Summit, MO
Reply to this email to reach us. To stop recruiting messages, reply UNSUBSCRIBE.""",
    """Hi {first_name},

Accord Group is reviewing candidates for {role}, and we'd love to speak with you for a brief 30-minute phone screen.

Book a time here:
{calendly_url}

Thank you,
Accord Group Recruiting

---
Reply UNSUBSCRIBE to stop recruiting messages.""",
]


def _pick_index(options: list[str], previous: str | None) -> int:
    if not previous or not previous.strip():
        return 0
    normalized = previous.strip()
    for i, tpl in enumerate(options):
        if tpl.strip() == normalized:
            return (i + 1) % len(options)
    return (hash(normalized) % len(options) + 1) % len(options)


def template_redraft_r1_sms(
    candidate: dict,
    calendly_url: str,
    *,
    previous_draft: str | None = None,
) -> str:
    fn = first_name(candidate.get("full_name") or "")
    idx = _pick_index(SMS_TEMPLATES, previous_draft)
    tpl = SMS_TEMPLATES[idx]
    try:
        return tpl.format(
            first_name=fn,
            role=ROLE_TITLE,
            calendly_url=calendly_url.strip(),
        ).strip()
    except KeyError:
        return build_r1_sms_body(candidate.get("full_name") or "Candidate", calendly_url)


def template_redraft_r1_email(
    candidate: dict,
    calendly_url: str,
    *,
    previous_subject: str | None = None,
    previous_body: str | None = None,
) -> tuple[str, str]:
    fn = first_name(candidate.get("full_name") or "")
    subj_idx = _pick_index(EMAIL_SUBJECT_TEMPLATES, previous_subject)
    body_idx = _pick_index(EMAIL_BODY_TEMPLATES, previous_body)
    subject = EMAIL_SUBJECT_TEMPLATES[subj_idx]
    try:
        body = EMAIL_BODY_TEMPLATES[body_idx].format(
            first_name=fn,
            role=ROLE_TITLE,
            calendly_url=calendly_url.strip(),
        ).strip()
    except KeyError:
        return build_r1_email_subject(), build_r1_email_body(
            candidate.get("full_name") or "Candidate",
            calendly_url,
        )
    return subject, body
