"""Round 1 SMS invite via Twilio + Calendly link."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.app_config import get_config
from lib.phone_utils import normalize_phone_us

DEFAULT_R1_SMS_TEMPLATE = """Hi {first_name} — Accord Group recruiting. You stood out for our Project Sales Representative role.

Would you have 30 min for a phone screen with our hiring team next week?

Book here: {calendly_url}

Reply STOP to opt out."""

MESSAGE_PLACEHOLDERS = ("{first_name}", "{full_name}", "{calendly_url}", "{role}")


def first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else "there"


def format_message_template(
    template: str,
    *,
    full_name: str,
    calendly_url: str,
    role: str | None = None,
) -> str:
    from lib.constants import ROLE_TITLE

    return template.format(
        first_name=first_name(full_name),
        full_name=full_name.strip(),
        calendly_url=calendly_url.strip(),
        role=role or ROLE_TITLE,
    )


def build_r1_sms_body(full_name: str, calendly_url: str, template: str | None = None) -> str:
    tpl = (template or DEFAULT_R1_SMS_TEMPLATE).strip()
    return format_message_template(tpl, full_name=full_name, calendly_url=calendly_url)


def get_calendly_r1_url() -> str:
    return get_config("CALENDLY_R1_URL")


def calendly_configured() -> bool:
    return bool(get_calendly_r1_url())


def twilio_configured() -> bool:
    sid = get_config("TWILIO_ACCOUNT_SID")
    token = get_config("TWILIO_AUTH_TOKEN")
    from_number = get_config("TWILIO_FROM_NUMBER")
    return bool(sid and sid.startswith("AC") and token and from_number)


def send_r1_sms(*, to_phone: str, body: str) -> str:
    """Send SMS; returns Twilio message SID."""
    from lib.communications_status import outbound_sends_enabled

    if not outbound_sends_enabled():
        raise RuntimeError("Outbound sends are disabled (OUTBOUND_SENDS_ENABLED=false).")

    from twilio.rest import Client

    to_e164 = normalize_phone_us(to_phone)
    if not to_e164:
        raise ValueError(f"Invalid phone number: {to_phone}")

    client = Client(get_config("TWILIO_ACCOUNT_SID"), get_config("TWILIO_AUTH_TOKEN"))
    from_number = get_config("TWILIO_FROM_NUMBER")
    if not from_number.startswith("+"):
        from_number = normalize_phone_us(from_number) or from_number

    message = client.messages.create(from_=from_number, to=to_e164, body=body)
    return message.sid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
