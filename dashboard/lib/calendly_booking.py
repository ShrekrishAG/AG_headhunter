"""Calendly booking sync — match invitee email → candidates.r1_scheduled_at + stage."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client

from lib.candidate_activity import log_activity, update_pipeline_stage
from lib.constants import STAGE_ORDER
from lib.email_utils import normalize_email

logger = logging.getLogger(__name__)

# Stages that Calendly booking may advance into round_1_scheduled.
_BOOKABLE_FROM = frozenset({"identified", "qualified", "outreached", "round_1_scheduled"})

DISPLAY_TZ = ZoneInfo("America/Chicago")


def verify_calendly_signature(
    raw_body: bytes,
    signature_header: str | None,
    signing_key: str,
    *,
    tolerance_seconds: int = 180,
) -> bool:
    """Verify Calendly-Webhook-Signature: t=<ts>,v1=<hex hmac of '{ts}.{body}'>."""
    if not signing_key or not signature_header:
        return False
    parts: dict[str, str] = {}
    for chunk in signature_header.split(","):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > tolerance_seconds:
        return False
    signed = f"{timestamp}.".encode("utf-8") + raw_body
    expected = hmac.new(
        signing_key.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    try:
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def format_booked_caption(r1_scheduled_at: str | None) -> str | None:
    """One-line Pipeline caption, e.g. 'Booked Tue Aug 5, 2:00 PM CT'."""
    if not r1_scheduled_at:
        return None
    try:
        raw = str(r1_scheduled_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(DISPLAY_TZ)
        hour = local.strftime("%I").lstrip("0") or "12"
        return (
            f"Booked {local.strftime('%a %b')} {local.day}, "
            f"{hour}:{local.strftime('%M %p')} CT"
        )
    except Exception:
        return f"Booked {str(r1_scheduled_at)[:16].replace('T', ' ')}"


def _stage_rank(stage: str | None) -> int:
    if not stage or stage not in STAGE_ORDER:
        return -1
    return STAGE_ORDER.index(stage)


def _extract_booking(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Calendly invitee webhook payload fields."""
    invitee = payload.get("payload") if "payload" in payload else payload
    if not isinstance(invitee, dict):
        invitee = {}
    email = normalize_email(invitee.get("email") or "")
    invitee_uri = (invitee.get("uri") or "").strip() or None
    scheduled = invitee.get("scheduled_event") or {}
    if not isinstance(scheduled, dict):
        scheduled = {}
    event_uri = (scheduled.get("uri") or "").strip() or None
    start_time = (scheduled.get("start_time") or invitee.get("start_time") or "").strip() or None
    name = (invitee.get("name") or "").strip() or None
    return {
        "email": email,
        "name": name,
        "invitee_uri": invitee_uri,
        "event_uri": event_uri,
        "start_time": start_time,
    }


def find_candidate_for_booking(
    sb: Client,
    *,
    email: str | None,
    invitee_uri: str | None = None,
) -> dict[str, Any] | None:
    if invitee_uri:
        rows = (
            sb.table("candidates")
            .select("*")
            .eq("calendly_invitee_uri", invitee_uri)
            .limit(5)
            .execute()
            .data
        )
        if rows:
            return rows[0]
    if not email:
        return None
    rows = (
        sb.table("candidates")
        .select("*")
        .ilike("email", email)
        .limit(20)
        .execute()
        .data
    ) or []
    matches = [r for r in rows if normalize_email(r.get("email") or "") == email]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    def sort_key(row: dict) -> tuple:
        stage = row.get("pipeline_stage") or ""
        # Prefer outreached / qualified / identified for booking attach
        prefer = 0 if stage in ("outreached", "qualified", "identified", "round_1_scheduled") else 1
        return (prefer, -_stage_rank(stage), str(row.get("updated_at") or ""))

    return sorted(matches, key=sort_key)[0]


def apply_invitee_created(sb: Client, body: dict[str, Any]) -> dict[str, Any]:
    booking = _extract_booking(body)
    email = booking["email"]
    if not email:
        return {"ok": False, "reason": "missing_email"}

    candidate = find_candidate_for_booking(
        sb, email=email, invitee_uri=booking["invitee_uri"]
    )
    if not candidate:
        logger.info("Calendly booking: no candidate for %s", email)
        return {"ok": False, "reason": "candidate_not_found", "email": email}

    patch: dict[str, Any] = {
        "r1_scheduled_at": booking["start_time"],
        "calendly_invitee_uri": booking["invitee_uri"],
        "calendly_event_uri": booking["event_uri"],
    }
    sb.table("candidates").update(patch).eq("id", candidate["id"]).execute()

    current = candidate.get("pipeline_stage") or "identified"
    advanced = False
    if current in _BOOKABLE_FROM and current != "round_1_scheduled":
        # Only advance when not already past phone screen
        if _stage_rank(current) < _stage_rank("round_1_scheduled"):
            update_pipeline_stage(
                sb,
                candidate["id"],
                "round_1_scheduled",
                from_stage=current,
                reason="calendly_invitee_created",
            )
            advanced = True
    elif current == "round_1_scheduled":
        pass

    log_activity(
        sb,
        candidate["id"],
        "calendly_booked",
        channel="calendly",
        actor="calendly",
        payload={
            "email": email,
            "name": booking["name"],
            "start_time": booking["start_time"],
            "invitee_uri": booking["invitee_uri"],
            "event_uri": booking["event_uri"],
            "stage_advanced": advanced,
        },
    )
    return {
        "ok": True,
        "candidate_id": candidate["id"],
        "full_name": candidate.get("full_name"),
        "advanced": advanced,
        "r1_scheduled_at": booking["start_time"],
    }


def apply_invitee_canceled(sb: Client, body: dict[str, Any]) -> dict[str, Any]:
    booking = _extract_booking(body)
    candidate = find_candidate_for_booking(
        sb, email=booking["email"], invitee_uri=booking["invitee_uri"]
    )
    if not candidate:
        return {
            "ok": False,
            "reason": "candidate_not_found",
            "email": booking["email"],
        }

    sb.table("candidates").update(
        {
            "r1_scheduled_at": None,
            "calendly_invitee_uri": None,
            "calendly_event_uri": None,
        }
    ).eq("id", candidate["id"]).execute()

    current = candidate.get("pipeline_stage") or ""
    reverted = False
    if current == "round_1_scheduled":
        update_pipeline_stage(
            sb,
            candidate["id"],
            "outreached",
            from_stage=current,
            reason="calendly_invitee_canceled",
        )
        reverted = True

    log_activity(
        sb,
        candidate["id"],
        "calendly_canceled",
        channel="calendly",
        actor="calendly",
        payload={
            "email": booking["email"],
            "invitee_uri": booking["invitee_uri"],
            "stage_reverted": reverted,
        },
    )
    return {
        "ok": True,
        "candidate_id": candidate["id"],
        "full_name": candidate.get("full_name"),
        "reverted": reverted,
    }


def handle_calendly_event(sb: Client, body: dict[str, Any]) -> dict[str, Any]:
    event = (body.get("event") or "").strip()
    if event == "invitee.created":
        return {"event": event, **apply_invitee_created(sb, body)}
    if event == "invitee.canceled":
        return {"event": event, **apply_invitee_canceled(sb, body)}
    return {"ok": True, "event": event, "reason": "ignored"}
