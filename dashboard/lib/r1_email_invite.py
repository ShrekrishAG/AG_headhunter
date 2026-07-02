"""Round 1 email invite via SendGrid + Calendly link."""

from __future__ import annotations

from lib.app_config import get_config
from lib.email_utils import normalize_email
from lib.r1_invite import first_name, format_message_template, get_calendly_r1_url

DEFAULT_R1_EMAIL_SUBJECT = "Accord Group — Project Sales Representative phone screen"

DEFAULT_R1_EMAIL_BODY = """Hi {first_name},

Thank you for your interest in the Project Sales Representative role at Accord Group. We'd like to invite you to a 30-minute phone screen with our hiring team.

Please pick a time that works for you:
{calendly_url}

Best,
Accord Group Recruiting

---
Accord Group · Lee's Summit, MO
Reply to this email to reach us. To stop recruiting messages, reply UNSUBSCRIBE."""


def build_r1_email_subject(
    template: str | None = None,
    *,
    full_name: str = "Candidate",
    calendly_url: str = "",
) -> str:
    tpl = (template or DEFAULT_R1_EMAIL_SUBJECT).strip()
    if "{" not in tpl:
        return tpl
    return format_message_template(
        tpl,
        full_name=full_name,
        calendly_url=calendly_url or get_calendly_r1_url(),
    )


def build_r1_email_body(
    full_name: str,
    calendly_url: str,
    template: str | None = None,
) -> str:
    tpl = (template or DEFAULT_R1_EMAIL_BODY).strip()
    return format_message_template(tpl, full_name=full_name, calendly_url=calendly_url)


def sendgrid_configured() -> bool:
    return bool(get_config("SENDGRID_API_KEY") and get_config("SENDGRID_FROM_EMAIL"))


def send_r1_email(*, to_email: str, subject: str, body: str) -> str:
    """Send plain-text R1 invite; returns SendGrid message id header if present."""
    from lib.communications_status import outbound_sends_enabled

    if not outbound_sends_enabled():
        raise RuntimeError("Outbound sends are disabled (OUTBOUND_SENDS_ENABLED=false).")

    normalized = normalize_email(to_email)
    if not normalized:
        raise ValueError(f"Invalid email address: {to_email}")

    api_key = get_config("SENDGRID_API_KEY")
    from_email = get_config("SENDGRID_FROM_EMAIL")
    from_name = get_config("SENDGRID_FROM_NAME", "Accord Group Recruiting")
    if not api_key or not from_email:
        raise RuntimeError("SendGrid not configured (SENDGRID_API_KEY, SENDGRID_FROM_EMAIL)")

    import sendgrid
    from sendgrid.helpers.mail import Email, Mail

    message = Mail(
        from_email=Email(from_email, from_name),
        to_emails=normalized,
        subject=subject.strip(),
        plain_text_content=body.strip(),
    )
    client = sendgrid.SendGridAPIClient(api_key)
    response = client.send(message)
    return response.headers.get("X-Message-Id", str(response.status_code))
