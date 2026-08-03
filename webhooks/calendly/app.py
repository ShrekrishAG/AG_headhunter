"""Calendly webhook HTTP service — POST /webhooks/calendly."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from supabase import create_client

WEBHOOKS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = WEBHOOKS_ROOT.parents[1]
DASHBOARD_ROOT = REPO_ROOT / "dashboard"

# Prefer dashboard/.env (shared secrets), then local overrides
load_dotenv(DASHBOARD_ROOT / ".env")
load_dotenv(WEBHOOKS_ROOT / ".env")

sys.path.insert(0, str(DASHBOARD_ROOT))

from lib.calendly_booking import handle_calendly_event, verify_calendly_signature  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendly-webhook")

app = FastAPI(title="Accord Headhunter Calendly Webhook", docs_url=None, redoc_url=None)


def _supabase():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")
    return create_client(url, key)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "calendly-webhook",
        "signing_key_configured": bool(
            os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "").strip()
        ),
        "supabase_configured": bool(
            os.getenv("SUPABASE_URL", "").strip()
            and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        ),
    }


@app.post("/webhooks/calendly")
async def calendly_webhook(
    request: Request,
    calendly_webhook_signature: str | None = Header(default=None),
) -> JSONResponse:
    raw = await request.body()
    signing_key = os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "").strip()
    # Optional bypass for local smoke tests only
    skip_verify = os.getenv("CALENDLY_SKIP_SIGNATURE_VERIFY", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if signing_key and not skip_verify:
        if not verify_calendly_signature(raw, calendly_webhook_signature, signing_key):
            raise HTTPException(status_code=401, detail="Invalid Calendly signature")
    elif not signing_key and not skip_verify:
        logger.warning("CALENDLY_WEBHOOK_SIGNING_KEY unset — rejecting webhook")
        raise HTTPException(status_code=503, detail="Webhook signing key not configured")

    try:
        body = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")

    try:
        sb = _supabase()
        result = handle_calendly_event(sb, body)
    except Exception:
        logger.exception("Calendly webhook handler failed")
        # Return 200 for unknown candidates already handled; true errors → 500 for retry
        raise HTTPException(status_code=500, detail="Handler error")

    # Always 200 when we processed (including candidate_not_found) so Calendly does not storm retries
    return JSONResponse(result)
