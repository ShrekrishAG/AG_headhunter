#!/usr/bin/env python3
"""Print Heymarket inbox and team IDs for dashboard/.env (no messages sent)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

DASHBOARD = Path(__file__).resolve().parents[1]
load_dotenv(DASHBOARD / ".env")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def auth_headers() -> dict[str, str]:
    legacy = os.getenv("HEYMARKET_API_KEY", "").strip()
    if legacy:
        return {"Authorization": f"Bearer {legacy}"}

    secret_id = os.getenv("HEYMARKET_API_SECRET_ID", "").strip()
    secret_key = os.getenv("HEYMARKET_API_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        raise RuntimeError("Set HEYMARKET_API_KEY or HEYMARKET_API_SECRET_ID + HEYMARKET_API_SECRET_KEY")

    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iss": secret_id, "iat": int(time.time())}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(
        hmac.new(f"{secret_id}||{secret_key}".encode(), signing_input, hashlib.sha256).digest()
    )
    return {"Authorization": f"Bearer {header}.{payload}.{sig}"}


def _get(path: str, headers: dict[str, str]) -> object:
    req = urllib.request.Request(f"https://api.heymarket.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _as_list(data: object) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("inboxes", "members", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return [data] if data else []


def main() -> int:
    try:
        headers = auth_headers()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        print(
            "\nAdd credentials to dashboard/.env first — see integrations/heymarket-setup.md\n",
            file=sys.stderr,
        )
        return 1

    print("══ Inboxes → put id in HEYMARKET_INBOX_ID ══\n")
    for inbox in _as_list(_get("/v1/inboxes", headers)):
        if not isinstance(inbox, dict):
            continue
        phones = ", ".join(inbox.get("phones") or []) or "—"
        print(f"  HEYMARKET_INBOX_ID={inbox.get('id')}")
        print(f"    name:    {inbox.get('name')}")
        print(f"    phones:  {phones}")
        print(f"    members: {inbox.get('members') or []}")
        print()

    print("══ Team members → put YOUR id in HEYMARKET_CREATOR_ID ══\n")
    team = _get("/v1/team", headers)
    for member in _as_list(team):
        if not isinstance(member, dict):
            continue
        print(f"  HEYMARKET_CREATOR_ID={member.get('id')}")
        print(f"    name:  {member.get('name')}")
        print(f"    email: {member.get('email')}")
        print()

    inbox_id = os.getenv("HEYMARKET_INBOX_ID", "").strip()
    creator_id = os.getenv("HEYMARKET_CREATOR_ID", "").strip()
    if inbox_id or creator_id:
        print("══ Already in your .env ══")
        print(f"  HEYMARKET_INBOX_ID={inbox_id or '(not set)'}")
        print(f"  HEYMARKET_CREATOR_ID={creator_id or '(not set)'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
