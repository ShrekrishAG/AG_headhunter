"""Heymarket SMS API client."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Any

from lib.app_config import get_config
from lib.phone_utils import normalize_phone_us

API_BASE = "https://api.heymarket.com"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def heymarket_auth_headers() -> dict[str, str]:
    legacy = get_config("HEYMARKET_API_KEY", "").strip()
    if legacy:
        return {"Authorization": f"Bearer {legacy}"}

    secret_id = get_config("HEYMARKET_API_SECRET_ID", "").strip()
    secret_key = get_config("HEYMARKET_API_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        raise RuntimeError("Heymarket credentials missing")

    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iss": secret_id, "iat": int(time.time())}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(
        hmac.new(f"{secret_id}||{secret_key}".encode(), signing_input, hashlib.sha256).digest()
    )
    return {"Authorization": f"Bearer {header}.{payload}.{sig}"}


def heymarket_configured() -> bool:
    if get_config("HEYMARKET_API_KEY", "").strip():
        return bool(get_config("HEYMARKET_INBOX_ID", "").strip())
    return bool(
        get_config("HEYMARKET_API_SECRET_ID", "").strip()
        and get_config("HEYMARKET_API_SECRET_KEY", "").strip()
        and get_config("HEYMARKET_INBOX_ID", "").strip()
        and (
            get_config("HEYMARKET_CREATOR_ID", "").strip()
            or get_config("HEYMARKET_CREATOR_EMAIL", "").strip()
        )
    )


def _heymarket_phone(to_phone: str) -> str:
    e164 = normalize_phone_us(to_phone)
    if not e164:
        raise ValueError(f"Invalid phone number: {to_phone}")
    return e164.lstrip("+")


def _post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    headers = heymarket_auth_headers()
    headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"Heymarket API {exc.code}: {detail or exc.reason}") from exc


def send_heymarket_sms(*, to_phone: str, body: str, conv_name: str | None = None) -> str:
    """Send SMS via Heymarket; returns message id as string."""
    inbox_id = get_config("HEYMARKET_INBOX_ID", "").strip()
    if not inbox_id:
        raise RuntimeError("HEYMARKET_INBOX_ID is not set")

    payload: dict[str, Any] = {
        "inbox_id": int(inbox_id),
        "phone_number": _heymarket_phone(to_phone),
        "text": body.strip(),
    }

    creator_email = get_config("HEYMARKET_CREATOR_EMAIL", "").strip()
    creator_id = get_config("HEYMARKET_CREATOR_ID", "").strip()
    if creator_email:
        payload["creator_email"] = creator_email
    elif creator_id:
        payload["creator_id"] = int(creator_id)
    else:
        raise RuntimeError("Set HEYMARKET_CREATOR_ID or HEYMARKET_CREATOR_EMAIL")

    if conv_name:
        payload["conv_name"] = conv_name.strip()

    result = _post_json("/v1/message/send", payload)
    message_id = result.get("id")
    if message_id is None:
        raise RuntimeError(f"Heymarket send returned unexpected response: {result}")
    return str(message_id)
