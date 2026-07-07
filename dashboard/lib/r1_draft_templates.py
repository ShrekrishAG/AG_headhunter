"""Template-based invite redrafts (no LLM API required)."""

from __future__ import annotations

from lib.constants import ROLE_TITLE
from lib.r1_email_invite import (
    DEFAULT_R1_EMAIL_BODY,
    DEFAULT_R1_EMAIL_SUBJECT,
    build_r1_email_body,
    build_r1_email_subject,
)
from lib.r1_invite import DEFAULT_R1_SMS_TEMPLATE, build_r1_sms_body


def _format_tpl(
    template: str,
    *,
    full_name: str,
    calendly_url: str,
    market: str | None,
) -> str:
    from lib.r1_invite import format_message_template

    return format_message_template(
        template,
        full_name=full_name,
        calendly_url=calendly_url,
        market=market,
        role=ROLE_TITLE,
    )


SMS_TEMPLATES = [
    DEFAULT_R1_SMS_TEMPLATE,
    """Hi {FirstName} — Accord Group is hiring in {Market}. Your ZipRecruiter profile caught our eye for Project Sales Rep. No roofing background required. Book a quick phone screen: {apply_url}

Reply STOP to opt out.""",
    """{FirstName}, Accord Group recruiting here. Strong match for our Project Sales Rep role in {Market}. Training provided. Schedule a call: {apply_url}

Reply STOP to opt out.""",
]

EMAIL_SUBJECT_TEMPLATES = [
    DEFAULT_R1_EMAIL_SUBJECT,
    "Accord Group — Project Sales Rep opportunity in {Market}",
    "Your ZipRecruiter profile — phone screen invite ({Market})",
]

EMAIL_BODY_TEMPLATES = [
    DEFAULT_R1_EMAIL_BODY,
    """Hi {FirstName},

Accord Group is hiring Project Sales Representatives in {Market}. Based on your ZipRecruiter resume, we'd like to invite you to a 30-minute phone screen.

Book here:
{apply_url}

Best,
Brittaney
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
    name = candidate.get("full_name") or "Candidate"
    market = candidate.get("market")
    idx = _pick_index(SMS_TEMPLATES, previous_draft)
    try:
        return _format_tpl(
            SMS_TEMPLATES[idx],
            full_name=name,
            calendly_url=calendly_url,
            market=market,
        ).strip()
    except Exception:
        return build_r1_sms_body(name, calendly_url, market=market)


def template_redraft_r1_email(
    candidate: dict,
    calendly_url: str,
    *,
    previous_subject: str | None = None,
    previous_body: str | None = None,
) -> tuple[str, str]:
    name = candidate.get("full_name") or "Candidate"
    market = candidate.get("market")
    subj_idx = _pick_index(EMAIL_SUBJECT_TEMPLATES, previous_subject)
    body_idx = _pick_index(EMAIL_BODY_TEMPLATES, previous_body)
    try:
        subject = _format_tpl(
            EMAIL_SUBJECT_TEMPLATES[subj_idx],
            full_name=name,
            calendly_url=calendly_url,
            market=market,
        ).strip()
        body = _format_tpl(
            EMAIL_BODY_TEMPLATES[body_idx],
            full_name=name,
            calendly_url=calendly_url,
            market=market,
        ).strip()
    except Exception:
        return (
            build_r1_email_subject(full_name=name, calendly_url=calendly_url, market=market),
            build_r1_email_body(name, calendly_url, market=market),
        )
    return subject, body
