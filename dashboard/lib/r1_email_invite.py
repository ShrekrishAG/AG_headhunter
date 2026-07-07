"""Round 1 email invite via SendGrid + Calendly link."""

from __future__ import annotations

from lib.app_config import get_config
from lib.email_utils import normalize_email
from lib.r1_invite import format_message_template, get_calendly_r1_url

DEFAULT_R1_EMAIL_SUBJECT = "ZipRecruiter match — sales role in {Market}"

DEFAULT_R1_EMAIL_BODY = """Hi {FirstName},

I'm reaching out from Accord Group's recruiting team. We're hiring Project Sales Representatives in {Market}, and your resume on ZipRecruiter matched what we're looking for.

Project Sales Reps help homeowners after storms — walking them through inspections, insurance claims, and restoration. You don't need roofing experience; Accord provides full training and ongoing support.

A few things candidates like about this role:
• Uncapped earning potential — your income follows your work ethic
• Paid training and a clear path to grow
• Licensed, insured employer (Inc. 5000 company)
• Meaningful work helping families recover after storms

Please book a phone screen with us if interested:
{apply_url}


Best,
Brittaney
Accord Group Recruiting

---
Reply UNSUBSCRIBE to stop recruiting messages."""


def build_r1_email_subject(
    template: str | None = None,
    *,
    full_name: str = "Candidate",
    calendly_url: str = "",
    market: str | None = None,
) -> str:
    tpl = (template or DEFAULT_R1_EMAIL_SUBJECT).strip()
    if "{" not in tpl:
        return tpl
    return format_message_template(
        tpl,
        full_name=full_name,
        calendly_url=calendly_url or get_calendly_r1_url(),
        market=market,
    )


def build_r1_email_body(
    full_name: str,
    calendly_url: str,
    template: str | None = None,
    *,
    market: str | None = None,
) -> str:
    tpl = (template or DEFAULT_R1_EMAIL_BODY).strip()
    return format_message_template(
        tpl,
        full_name=full_name,
        calendly_url=calendly_url,
        market=market,
    )


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
