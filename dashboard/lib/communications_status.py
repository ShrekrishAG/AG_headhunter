"""Integration status for Calendly, Twilio SMS, and SendGrid email."""

from __future__ import annotations

from lib.app_config import get_config
from lib.r1_email_invite import sendgrid_configured
from lib.r1_invite import get_calendly_r1_url, twilio_configured


def outbound_sends_enabled() -> bool:
    """Pipeline Send SMS / Send email buttons. Default off — set OUTBOUND_SENDS_ENABLED=true to allow."""
    return get_config("OUTBOUND_SENDS_ENABLED", "false").lower() in ("1", "true", "yes")


def calendly_configured() -> bool:
    return bool(get_calendly_r1_url())


def sms_ready() -> bool:
    return outbound_sends_enabled() and calendly_configured() and twilio_configured()


def email_ready() -> bool:
    return outbound_sends_enabled() and calendly_configured() and sendgrid_configured()


def integration_rows() -> list[dict]:
    cal_url = get_calendly_r1_url()
    rows = [
        {
            "name": "Calendly",
            "key": "CALENDLY_R1_URL",
            "configured": calendly_configured(),
            "detail": cal_url[:60] + "…" if cal_url and len(cal_url) > 60 else (cal_url or "Not set"),
            "required_for": "SMS + email booking links",
        },
        {
            "name": "Twilio SMS",
            "key": "TWILIO_*",
            "configured": twilio_configured(),
            "detail": _mask(get_config("TWILIO_FROM_NUMBER")) or "Missing SID / token / from number",
            "required_for": "Send SMS from Pipeline",
        },
        {
            "name": "SendGrid email",
            "key": "SENDGRID_*",
            "configured": sendgrid_configured(),
            "detail": get_config("SENDGRID_FROM_EMAIL") or "Missing API key or from email",
            "required_for": "Send email from Pipeline",
        },
    ]
    return rows


def _mask(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 4:
        return v
    return v[:2] + "…" + v[-2:]
