"""Schedule manager-packet emails for later send (local JSON queue + poller)."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import Client

from lib.manager_packets import (
    EXPORTS_ROOT,
    AssignmentPreview,
    build_assignment_preview,
    send_all_packets,
)

logger = logging.getLogger(__name__)

CT = ZoneInfo("America/Chicago")
DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = DASHBOARD_ROOT / "data" / "scheduled_packet_sends.json"

_lock = threading.Lock()
_worker_started = False
_worker_stop = threading.Event()

STATUSES_ACTIVE = frozenset({"scheduled", "sending"})


def _ensure_store() -> Path:
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SCHEDULE_PATH.is_file():
        SCHEDULE_PATH.write_text("[]\n", encoding="utf-8")
    return SCHEDULE_PATH


def _read_jobs() -> list[dict[str, Any]]:
    path = _ensure_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_jobs(jobs: list[dict[str, Any]]) -> None:
    path = _ensure_store()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_scheduled_jobs(*, include_done: bool = True) -> list[dict[str, Any]]:
    with _lock:
        jobs = _read_jobs()
    if not include_done:
        jobs = [j for j in jobs if j.get("status") in STATUSES_ACTIVE]
    jobs.sort(key=lambda j: j.get("send_at") or "")
    return jobs


def parse_local_send_at(date_value, time_value) -> datetime:
    """Combine Streamlit date/time inputs into timezone-aware CT datetime."""
    if hasattr(time_value, "hour"):
        hour, minute = time_value.hour, time_value.minute
    else:
        parts = str(time_value).split(":")
        hour, minute = int(parts[0]), int(parts[1])
    naive = datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
        0,
    )
    return naive.replace(tzinfo=CT)


def schedule_packet_send(
    *,
    export_batch: str,
    send_at: datetime,
    packet_count: int,
    candidate_count: int,
    test_mode: bool = False,
    redirect_to: str | None = None,
    created_by: str = "streamlit",
) -> dict[str, Any]:
    if not export_batch:
        raise ValueError("export_batch is required")
    export_dir = EXPORTS_ROOT / export_batch
    if not (export_dir / "candidates.csv").is_file():
        raise FileNotFoundError(f"Export batch not found: {export_batch}")

    if send_at.tzinfo is None:
        send_at = send_at.replace(tzinfo=CT)
    else:
        send_at = send_at.astimezone(CT)

    now = datetime.now(CT)
    if send_at <= now:
        raise ValueError("Send time must be in the future (Central Time).")

    redirect = (redirect_to or "").strip() if test_mode else None
    if test_mode and not redirect:
        raise ValueError("Test mode requires a redirect email.")

    job = {
        "id": uuid.uuid4().hex[:12],
        "export_batch": export_batch,
        "send_at": send_at.isoformat(),
        "status": "scheduled",
        "test_mode": bool(test_mode),
        "redirect_to": redirect,
        "record_sends": not test_mode,
        "packet_count": packet_count,
        "candidate_count": candidate_count,
        "created_at": now.isoformat(),
        "created_by": created_by,
        "started_at": None,
        "finished_at": None,
        "successes": [],
        "errors": [],
        "error_message": None,
    }
    with _lock:
        jobs = _read_jobs()
        # One active schedule per batch (avoid duplicate live sends).
        for existing in jobs:
            if (
                existing.get("export_batch") == export_batch
                and existing.get("status") in STATUSES_ACTIVE
                and not existing.get("test_mode")
                and not test_mode
            ):
                raise ValueError(
                    f"Batch {export_batch} already has a scheduled live send "
                    f"({existing.get('id')} at {existing.get('send_at')}). "
                    "Cancel it first."
                )
        jobs.append(job)
        _write_jobs(jobs)
    logger.info(
        "Scheduled packet send id=%s batch=%s at=%s test=%s",
        job["id"],
        export_batch,
        job["send_at"],
        test_mode,
    )
    return job


def cancel_scheduled_job(job_id: str) -> bool:
    with _lock:
        jobs = _read_jobs()
        changed = False
        for job in jobs:
            if job.get("id") == job_id and job.get("status") == "scheduled":
                job["status"] = "cancelled"
                job["finished_at"] = datetime.now(CT).isoformat()
                changed = True
                break
        if changed:
            _write_jobs(jobs)
        return changed


def _update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        jobs = _read_jobs()
        for job in jobs:
            if job.get("id") == job_id:
                job.update(fields)
                break
        _write_jobs(jobs)


def _due_job_ids(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(CT)
    due: list[str] = []
    with _lock:
        for job in _read_jobs():
            if job.get("status") != "scheduled":
                continue
            try:
                send_at = datetime.fromisoformat(job["send_at"])
            except (KeyError, ValueError, TypeError):
                continue
            if send_at.tzinfo is None:
                send_at = send_at.replace(tzinfo=CT)
            if send_at <= now:
                due.append(job["id"])
    return due


def process_due_jobs(sb: Client | None = None) -> list[dict[str, Any]]:
    """Send any scheduled jobs whose send_at has passed. Returns result summaries."""
    results: list[dict[str, Any]] = []
    for job_id in _due_job_ids():
        results.append(_run_job(job_id, sb=sb))
    return results


def _get_supabase_client() -> Client:
    load_dotenv(DASHBOARD_ROOT / ".env")
    from lib.supabase_client import get_supabase

    return get_supabase()


def _run_job(job_id: str, *, sb: Client | None = None) -> dict[str, Any]:
    with _lock:
        jobs = _read_jobs()
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job is None or job.get("status") != "scheduled":
            return {"id": job_id, "status": "skipped"}
        job["status"] = "sending"
        job["started_at"] = datetime.now(CT).isoformat()
        _write_jobs(jobs)
        snapshot = dict(job)

    export_batch = snapshot["export_batch"]
    export_dir = EXPORTS_ROOT / export_batch
    redirect = snapshot.get("redirect_to") if snapshot.get("test_mode") else None
    record_sends = bool(snapshot.get("record_sends", True))

    try:
        client = sb or _get_supabase_client()
        preview: AssignmentPreview = build_assignment_preview(client, export_dir)
        if not preview.packets:
            raise RuntimeError(
                "No packets to send for this batch "
                "(already sent or no configured markets)."
            )
        successes, errors = send_all_packets(
            client,
            preview.packets,
            redirect_to=redirect,
            record_sends=record_sends and not snapshot.get("test_mode"),
        )
        status = "sent" if successes and not errors else ("failed" if not successes else "sent")
        if successes and errors:
            status = "partial"
        _update_job(
            job_id,
            status=status,
            finished_at=datetime.now(CT).isoformat(),
            successes=successes,
            errors=errors,
            packet_count=len(preview.packets),
            error_message=None if successes else "; ".join(errors)[:500],
        )
        logger.info(
            "Scheduled packet job %s finished status=%s ok=%s err=%s",
            job_id,
            status,
            len(successes),
            len(errors),
        )
        return {
            "id": job_id,
            "status": status,
            "successes": successes,
            "errors": errors,
            "export_batch": export_batch,
        }
    except Exception as exc:
        logger.exception("Scheduled packet job %s failed", job_id)
        _update_job(
            job_id,
            status="failed",
            finished_at=datetime.now(CT).isoformat(),
            error_message=str(exc)[:500],
            errors=[str(exc)],
        )
        return {
            "id": job_id,
            "status": "failed",
            "errors": [str(exc)],
            "export_batch": export_batch,
        }


def format_send_at_display(iso_value: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CT)
        else:
            dt = dt.astimezone(CT)
        return dt.strftime("%b %d, %Y · %I:%M %p CT").lstrip("0").replace(" 0", " ")
    except ValueError:
        return iso_value


def default_schedule_suggestion(*, minutes_from_now: int = 5) -> datetime:
    """Round up to next minute + buffer for a quick try."""
    now = datetime.now(CT) + timedelta(minutes=max(1, minutes_from_now))
    return now.replace(second=0, microsecond=0)


def start_scheduled_packet_worker(*, interval_seconds: float = 20.0) -> None:
    """Background poller — call once from Streamlit app startup."""
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop() -> None:
        logger.info(
            "Manager packet schedule worker started (every %.0fs)", interval_seconds
        )
        while not _worker_stop.wait(interval_seconds):
            try:
                if _due_job_ids():
                    process_due_jobs()
            except Exception:
                logger.exception("Packet schedule worker tick failed")

    thread = threading.Thread(
        target=_loop,
        name="manager-packet-scheduler",
        daemon=True,
    )
    thread.start()
