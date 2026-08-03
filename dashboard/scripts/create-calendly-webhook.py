#!/usr/bin/env python3
"""Create a Calendly webhook subscription (invitee.created + invitee.canceled).

Requires:
  CALENDLY_PAT          — personal access token
  CALENDLY_WEBHOOK_URL  — public HTTPS URL ending in /webhooks/calendly
  CALENDLY_ORGANIZATION_URI or CALENDLY_USER_URI

Prints the signing_key — store as CALENDLY_WEBHOOK_SIGNING_KEY.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import urllib.request

from dotenv import load_dotenv

DASHBOARD = Path(__file__).resolve().parents[1]
load_dotenv(DASHBOARD / ".env")
load_dotenv(DASHBOARD.parent / "webhooks" / "calendly" / ".env")


def main() -> int:
    token = os.getenv("CALENDLY_PAT", "").strip()
    url = os.getenv("CALENDLY_WEBHOOK_URL", "").strip()
    org = os.getenv("CALENDLY_ORGANIZATION_URI", "").strip()
    user = os.getenv("CALENDLY_USER_URI", "").strip()
    if not token or not url:
        print("Set CALENDLY_PAT and CALENDLY_WEBHOOK_URL", file=sys.stderr)
        return 1
    if not org and not user:
        print("Set CALENDLY_ORGANIZATION_URI or CALENDLY_USER_URI", file=sys.stderr)
        return 1

    body: dict = {
        "url": url,
        "events": ["invitee.created", "invitee.canceled"],
        "scope": "organization" if org else "user",
    }
    if org:
        body["organization"] = org
    else:
        body["user"] = user

    req = urllib.request.Request(
        "https://api.calendly.com/webhook_subscriptions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        if hasattr(exc, "read"):
            print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1

    resource = data.get("resource") or data
    signing_key = resource.get("signing_key")
    print(json.dumps(resource, indent=2))
    if signing_key:
        print("\nAdd to dashboard/.env and webhook host env:")
        print(f"CALENDLY_WEBHOOK_SIGNING_KEY={signing_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
