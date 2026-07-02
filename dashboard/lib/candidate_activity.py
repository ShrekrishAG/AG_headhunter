"""Candidate activity log — outreach, stage changes, and timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client

BODY_PREVIEW_MAX = 200

ACTIVITY_LABELS: dict[str, str] = {
    "sms_sent": "SMS sent",
    "email_sent": "Email sent",
    "sms_failed": "SMS failed",
    "email_failed": "Email failed",
    "stage_changed": "Stage changed",
    "r1_evaluation_saved": "R1 scorecard saved",
    "contact_updated": "Contact updated",
    "outreach_draft_generated": "Outreach draft (reference)",
}


def is_contacted(candidate: dict) -> bool:
    sms = int(candidate.get("sms_outreach_count") or 0)
    email = int(candidate.get("email_outreach_count") or 0)
    return sms > 0 or email > 0


def apply_outreach_stage(
    sb: Client,
    candidate_id: str,
    current_stage: str,
    *,
    reason: str,
) -> bool:
    """Move to outreached after invite send unless already scheduled or later."""
    from lib.constants import OUTREACH_STAGE, STAGES_AT_OR_PAST_PHONE_SCHEDULED

    if current_stage in STAGES_AT_OR_PAST_PHONE_SCHEDULED or current_stage == OUTREACH_STAGE:
        return False
    update_pipeline_stage(
        sb,
        candidate_id,
        OUTREACH_STAGE,
        from_stage=current_stage,
        reason=reason,
    )
    return True


def tracking_available(sb: Client) -> bool:
    try:
        sb.table("candidate_activities").select("id").limit(1).execute()
        sb.table("candidates").select("sms_outreach_count, email_outreach_count").limit(1).execute()
        return True
    except Exception:
        return False


def _preview(text: str) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= BODY_PREVIEW_MAX:
        return cleaned
    return cleaned[:BODY_PREVIEW_MAX] + "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_activity(
    sb: Client,
    candidate_id: str,
    activity_type: str,
    *,
    channel: str | None = None,
    actor: str = "dashboard",
    payload: dict[str, Any] | None = None,
) -> None:
    if not tracking_available(sb):
        return
    sb.table("candidate_activities").insert(
        {
            "candidate_id": candidate_id,
            "activity_type": activity_type,
            "channel": channel,
            "actor": actor,
            "payload": payload or {},
        }
    ).execute()
    sb.table("candidates").update({"last_activity_at": _now_iso()}).eq("id", candidate_id).execute()


def log_sms_sent(
    sb: Client,
    candidate_id: str,
    *,
    to_phone: str,
    body: str,
    external_id: str | None = None,
    bulk: bool = False,
    phone: str | None = None,
) -> None:
    now = _now_iso()
    updates: dict[str, Any] = {"r1_invite_sent_at": now}
    if phone:
        updates["phone"] = phone
    if tracking_available(sb):
        row = (
            sb.table("candidates")
            .select("sms_outreach_count")
            .eq("id", candidate_id)
            .single()
            .execute()
            .data
        )
        count = int(row.get("sms_outreach_count") or 0) + 1
        updates.update(
            {
                "sms_outreach_count": count,
                "last_sms_at": now,
                "last_activity_at": now,
            }
        )
    sb.table("candidates").update(updates).eq("id", candidate_id).execute()
    if not tracking_available(sb):
        return
    count = int(updates.get("sms_outreach_count", 1))
    log_activity(
        sb,
        candidate_id,
        "sms_sent",
        channel="sms",
        payload={
            "to": to_phone,
            "body_preview": _preview(body),
            "external_id": external_id,
            "outreach_number": count,
            "bulk": bulk,
        },
    )


def log_email_sent(
    sb: Client,
    candidate_id: str,
    *,
    to_email: str,
    subject: str,
    body: str,
    external_id: str | None = None,
    bulk: bool = False,
    email: str | None = None,
) -> None:
    now = _now_iso()
    updates: dict[str, Any] = {"r1_invite_sent_at": now}
    if email:
        updates["email"] = email
    if tracking_available(sb):
        row = (
            sb.table("candidates")
            .select("email_outreach_count")
            .eq("id", candidate_id)
            .single()
            .execute()
            .data
        )
        count = int(row.get("email_outreach_count") or 0) + 1
        updates.update(
            {
                "email_outreach_count": count,
                "last_email_at": now,
                "last_activity_at": now,
            }
        )
    sb.table("candidates").update(updates).eq("id", candidate_id).execute()
    if not tracking_available(sb):
        return
    count = int(updates.get("email_outreach_count", 1))
    log_activity(
        sb,
        candidate_id,
        "email_sent",
        channel="email",
        payload={
            "to": to_email,
            "subject": subject,
            "body_preview": _preview(body),
            "external_id": external_id,
            "outreach_number": count,
            "bulk": bulk,
        },
    )


def log_outreach_failed(
    sb: Client,
    candidate_id: str,
    *,
    channel: str,
    error: str,
    bulk: bool = False,
) -> None:
    activity_type = "sms_failed" if channel == "sms" else "email_failed"
    log_activity(
        sb,
        candidate_id,
        activity_type,
        channel=channel,
        payload={"error": error, "bulk": bulk},
    )


def log_stage_change(
    sb: Client,
    candidate_id: str,
    *,
    from_stage: str,
    to_stage: str,
    reason: str | None = None,
) -> None:
    if from_stage == to_stage:
        return
    log_activity(
        sb,
        candidate_id,
        "stage_changed",
        channel="system",
        payload={"from": from_stage, "to": to_stage, "reason": reason},
    )


def update_pipeline_stage(
    sb: Client,
    candidate_id: str,
    new_stage: str,
    *,
    from_stage: str | None = None,
    reason: str | None = None,
) -> None:
    if from_stage is None:
        row = (
            sb.table("candidates")
            .select("pipeline_stage")
            .eq("id", candidate_id)
            .single()
            .execute()
            .data
        )
        from_stage = row["pipeline_stage"]
    if from_stage == new_stage:
        return
    sb.table("candidates").update({"pipeline_stage": new_stage}).eq("id", candidate_id).execute()
    if tracking_available(sb):
        log_stage_change(sb, candidate_id, from_stage=from_stage, to_stage=new_stage, reason=reason)


def log_outreach_draft_generated(
    sb: Client,
    candidate_id: str,
    *,
    sms_body: str,
    email_subject: str,
    email_body: str,
    export_batch: str | None = None,
) -> None:
    log_activity(
        sb,
        candidate_id,
        "outreach_draft_generated",
        channel="system",
        actor="agent",
        payload={
            "sms_body": sms_body,
            "email_subject": email_subject,
            "email_body": email_body,
            "export_batch": export_batch,
        },
    )


def has_outreach_draft(sb: Client, candidate_id: str) -> bool:
    if not tracking_available(sb):
        return False
    rows = (
        sb.table("candidate_activities")
        .select("id")
        .eq("candidate_id", candidate_id)
        .eq("activity_type", "outreach_draft_generated")
        .limit(1)
        .execute()
        .data
    )
    return bool(rows)


def latest_outreach_draft(activities: list[dict]) -> dict | None:
    for activity in activities:
        if activity.get("activity_type") == "outreach_draft_generated":
            return activity
    return None


def log_r1_evaluation_saved(
    sb: Client,
    candidate_id: str,
    *,
    interviewer: str,
    vote: str | None,
    weighted_score: float | None,
) -> None:
    log_activity(
        sb,
        candidate_id,
        "r1_evaluation_saved",
        channel="system",
        payload={
            "interviewer": interviewer,
            "vote": vote,
            "weighted_score": weighted_score,
        },
    )


def load_activities_by_candidate(
    sb: Client,
    candidate_ids: list[str],
    *,
    limit_per_candidate: int = 15,
) -> dict[str, list[dict]]:
    if not candidate_ids or not tracking_available(sb):
        return {}
    rows = (
        sb.table("candidate_activities")
        .select("*")
        .in_("candidate_id", candidate_ids)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    grouped: dict[str, list[dict]] = {cid: [] for cid in candidate_ids}
    for row in rows:
        cid = row["candidate_id"]
        if cid in grouped and len(grouped[cid]) < limit_per_candidate:
            grouped[cid].append(row)
    return grouped


def format_outreach_summary(candidate: dict) -> str:
    parts: list[str] = []
    sms_count = int(candidate.get("sms_outreach_count") or 0)
    email_count = int(candidate.get("email_outreach_count") or 0)
    if sms_count:
        parts.append(f"SMS ×{sms_count}")
    if email_count:
        parts.append(f"Email ×{email_count}")
    if not parts:
        return "No outreach yet"
    last = candidate.get("last_activity_at") or candidate.get("r1_invite_sent_at")
    if last:
        parts.append(f"last {str(last)[:10]}")
    return " · ".join(parts)


def format_activity_line(activity: dict, stage_labels: dict[str, str] | None = None) -> str:
    labels = stage_labels or {}
    activity_type = activity.get("activity_type") or ""
    label = ACTIVITY_LABELS.get(activity_type, activity_type.replace("_", " ").title())
    payload = activity.get("payload") or {}
    created = str(activity.get("created_at") or "")[:16].replace("T", " ")

    if activity_type == "stage_changed":
        from_stage = labels.get(payload.get("from"), payload.get("from"))
        to_stage = labels.get(payload.get("to"), payload.get("to"))
        detail = f"{from_stage} → {to_stage}"
    elif activity_type == "sms_sent":
        detail = f"to {payload.get('to', '—')} (#{payload.get('outreach_number', '?')})"
    elif activity_type == "email_sent":
        detail = f"\"{payload.get('subject', '—')}\" (#{payload.get('outreach_number', '?')})"
    elif activity_type in ("sms_failed", "email_failed"):
        detail = payload.get("error", "unknown error")
    elif activity_type == "r1_evaluation_saved":
        detail = f"{payload.get('interviewer', '—')} · vote {payload.get('vote', '—')}"
    elif activity_type == "outreach_draft_generated":
        detail = "SMS + email saved for reference (not sent)"
    else:
        detail = ""

    if payload.get("bulk"):
        detail = f"{detail} (bulk)".strip()
    return f"**{created}** — {label}" + (f" — {detail}" if detail else "")
