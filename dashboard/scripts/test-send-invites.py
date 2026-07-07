#!/usr/bin/env python3
"""Send test R1 SMS and/or email to Sample cand (or --phone/--email overrides)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from dotenv import load_dotenv

load_dotenv(DASHBOARD / ".env")

from lib.communications_status import email_ready, outbound_sends_enabled, sms_ready  # noqa: E402
from lib.r1_email_invite import build_r1_email_body, build_r1_email_subject, send_r1_email  # noqa: E402
from lib.r1_invite import build_r1_sms_body, get_calendly_r1_url, send_r1_sms  # noqa: E402

DEFAULT_PHONE = "+14085150245"
DEFAULT_EMAIL = "shreya@dollfamilyoffice.com"
DEFAULT_NAME = "Sample cand"


DEFAULT_MARKET = "TGC - KC, MO"


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Heymarket SMS and SendGrid email")
    parser.add_argument("--sms", action="store_true", help="Send test SMS")
    parser.add_argument("--email", action="store_true", help="Send test email")
    parser.add_argument("--phone", default=DEFAULT_PHONE)
    parser.add_argument("--to-email", dest="to_email", default=DEFAULT_EMAIL)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--market", default=DEFAULT_MARKET, help="ZipRecruiter market / project name")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.sms and not args.email:
        args.sms = args.email = True

    cal = get_calendly_r1_url()
    if not cal:
        print("Missing CALENDLY_R1_URL", file=sys.stderr)
        return 1

    failed = 0

    if args.sms:
        if not sms_ready():
            if not outbound_sends_enabled():
                print("SMS blocked — OUTBOUND_SENDS_ENABLED=false (set true in .env to send)")
            else:
                print("SMS not ready — check HEYMARKET_* or TWILIO_* and CALENDLY_R1_URL")
            failed += 1
        else:
            body = build_r1_sms_body(args.name, cal, market=args.market)
            print(f"SMS to {args.phone}:\n{body}\n")
            if args.dry_run:
                print("(dry-run — not sent)")
            else:
                try:
                    sid = send_r1_sms(to_phone=args.phone, body=body, conv_name=args.name)
                    print(f"SMS sent — SID {sid}")
                except Exception as exc:
                    print(f"SMS failed: {exc}")
                    failed += 1

    if args.email:
        if not email_ready():
            if not outbound_sends_enabled():
                print("Email blocked — OUTBOUND_SENDS_ENABLED=false (set true in .env to send)")
            else:
                print("Email not ready — check SENDGRID_* and CALENDLY_R1_URL")
            failed += 1
        else:
            subject = build_r1_email_subject(
                full_name=args.name,
                calendly_url=cal,
                market=args.market,
            )
            body = build_r1_email_body(args.name, cal, market=args.market)
            print(f"Email to {args.to_email}\nSubject: {subject}\n{body}\n")
            if args.dry_run:
                print("(dry-run — not sent)")
            else:
                try:
                    msg_id = send_r1_email(
                        to_email=args.to_email,
                        subject=subject,
                        body=body,
                    )
                    print(f"Email sent — id {msg_id}")
                except Exception as exc:
                    print(f"Email failed: {exc}")
                    failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
