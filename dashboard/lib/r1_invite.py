"""Round 1 SMS invite via Heymarket (or Twilio fallback) + Calendly link."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.app_config import get_config
from lib.outreach_market import outreach_market_label
from lib.phone_utils import normalize_phone_us

DEFAULT_R1_SMS_TEMPLATE = """Hi {FirstName} — Accord Group is hiring Project Sales Reps in {Market}. Your ZipRecruiter profile matched our search. No roofing exp needed. Book a phone screen and learn more: {apply_url}

Reply STOP to opt out."""

MESSAGE_PLACEHOLDERS = (
    "{FirstName}",
    "{first_name}",
    "{Market}",
    "{market}",
    "{apply_url}",
    "{calendly_url}",
    "{full_name}",
    "{role}",
)


def first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else "there"


def format_message_template(
    template: str,
    *,
    full_name: str,
    calendly_url: str,
    market: str | None = None,
    role: str | None = None,
) -> str:
    from lib.constants import ROLE_TITLE

    fn = first_name(full_name)
    market_label = outreach_market_label(market)
    apply_url = calendly_url.strip()
    role_title = role or ROLE_TITLE

    values = {
        "FirstName": fn,
        "first_name": fn,
        "full_name": full_name.strip(),
        "Market": market_label,
        "market": market_label,
        "apply_url": apply_url,
        "calendly_url": apply_url,
        "role": role_title,
    }
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", value)
    return result


def build_r1_sms_body(
    full_name: str,
    calendly_url: str,
    template: str | None = None,
    *,
    market: str | None = None,
) -> str:
    tpl = (template or DEFAULT_R1_SMS_TEMPLATE).strip()
    return format_message_template(
        tpl,
        full_name=full_name,
        calendly_url=calendly_url,
        market=market,
    )


def get_calendly_r1_url() -> str:
    return get_config("CALENDLY_R1_URL")


def calendly_configured() -> bool:
    return bool(get_calendly_r1_url())


def sms_provider_configured() -> bool:
    from lib.heymarket_client import heymarket_configured

    return heymarket_configured() or twilio_configured()


def twilio_configured() -> bool:
    sid = get_config("TWILIO_ACCOUNT_SID")
    token = get_config("TWILIO_AUTH_TOKEN")
    from_number = get_config("TWILIO_FROM_NUMBER")
    return bool(sid and sid.startswith("AC") and token and from_number)


def send_r1_sms(*, to_phone: str, body: str, conv_name: str | None = None) -> str:
    """Send SMS; returns provider message id."""
    from lib.communications_status import outbound_sends_enabled
    from lib.heymarket_client import heymarket_configured, send_heymarket_sms

    if not outbound_sends_enabled():
        raise RuntimeError("Outbound sends are disabled (OUTBOUND_SENDS_ENABLED=false).")

    if heymarket_configured():
        return send_heymarket_sms(to_phone=to_phone, body=body, conv_name=conv_name)

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
