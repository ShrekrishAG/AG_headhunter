"""Format ZipRecruiter export timestamps for the dashboard."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")


def export_tracking_available(sb) -> bool:
    try:
        sb.table("candidates").select("exported_at, export_batch").limit(1).execute()
        return True
    except Exception:
        return False


def parse_export_batch(batch: str | None) -> datetime | None:
    """Parse folder name like 2026-07-06_101925 (local export time)."""
    batch = (batch or "").strip()
    if not batch:
        return None
    try:
        return datetime.strptime(batch, "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None


def parse_export_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_export_datetime(
    candidate: dict,
    *,
    activities: list[dict] | None = None,
) -> datetime | None:
    ts = parse_export_timestamp(candidate.get("exported_at"))
    if ts is not None:
        return ts
    batch_ts = parse_export_batch(candidate.get("export_batch"))
    if batch_ts is not None:
        return batch_ts.replace(tzinfo=CHICAGO)
    if activities:
        for activity in activities:
            if activity.get("activity_type") != "outreach_draft_generated":
                continue
            batch = (activity.get("payload") or {}).get("export_batch")
            batch_ts = parse_export_batch(batch)
            if batch_ts is not None:
                return batch_ts.replace(tzinfo=CHICAGO)
    return None


def format_exported_display(
    candidate: dict,
    *,
    activities: list[dict] | None = None,
) -> str:
    ts = resolve_export_datetime(candidate, activities=activities)
    if ts is None:
        return "—"
    local = ts.astimezone(CHICAGO) if ts.tzinfo else ts.replace(tzinfo=CHICAGO)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%b %d, %Y')} · {hour}:{local.strftime('%M %p')} CT"
