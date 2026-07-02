#!/usr/bin/env python3
"""Check Calendly, Twilio, and SendGrid configuration (no messages sent)."""

from __future__ import annotations

import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from dotenv import load_dotenv

load_dotenv(DASHBOARD / ".env")

from lib.communications_status import (  # noqa: E402
    calendly_configured,
    email_ready,
    integration_rows,
    outbound_sends_enabled,
    sms_ready,
)
from lib.r1_invite import get_calendly_r1_url


def main() -> int:
    print("Accord Headhunter — communications check\n")
    for row in integration_rows():
        status = "OK" if row["configured"] else "MISSING"
        print(f"  [{status:7}] {row['name']:14} {row['detail']}")

    print()
    print(f"  Calendly URL: {get_calendly_r1_url() or '(not set)'}")
    print(f"  Outbound sends:   {'enabled' if outbound_sends_enabled() else 'DISABLED'}")
    print(f"  SMS send ready:   {'yes' if sms_ready() else 'no'}")
    print(f"  Email send ready: {'yes' if email_ready() else 'no'}")

    if not calendly_configured():
        print("\nSet CALENDLY_R1_URL in dashboard/.env")
        return 1
    if not outbound_sends_enabled():
        print("\nOutbound sends are disabled (OUTBOUND_SENDS_ENABLED=false). Pipeline Send buttons are off.")
        return 0
    if not sms_ready() and not email_ready():
        print("\nAdd Twilio and/or SendGrid credentials to enable sending.")
        return 1
    print("\nAt least one send channel is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
