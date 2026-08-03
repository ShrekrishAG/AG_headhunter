"""Build scored CSV exports from Pipeline candidates, filterable by export batch/date."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lib.agent_prescreen import parse_agent_recommendation, parse_agent_score
from lib.constants import DASHBOARD_ROOT
from lib.email_utils import normalize_email
from lib.export_display import CHICAGO, format_exported_display, parse_export_batch, resolve_export_datetime

logger = logging.getLogger(__name__)

EXPORTS_ROOT = DASHBOARD_ROOT.parent / "slack-zr-agent" / "exports"

CSV_COLUMNS = [
    "name",
    "email",
    "phone",
    "market",
    "score",
    "recommendation",
    "stage",
    "export_batch",
    "exported_at",
    "source",
    "pipeline_stage",
    "project_name",
]


def list_local_export_batches(*, limit: int = 40) -> list[dict[str, Any]]:
    """Batches from slack-zr-agent/exports folders (works without DB columns)."""
    if not EXPORTS_ROOT.is_dir():
        return []
    batches: list[dict[str, Any]] = []
    for path in sorted(EXPORTS_ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        csv_path = path / "candidates.csv"
        if not csv_path.is_file():
            continue
        batch_ts = parse_export_batch(path.name)
        count = 0
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                count = sum(1 for _ in csv.DictReader(handle))
        except OSError:
            continue
        display = (
            batch_ts.strftime("%b %d, %Y · %I:%M %p").lstrip("0").replace(" 0", " ")
            if batch_ts
            else path.name
        )
        batches.append(
            {
                "batch": path.name,
                "path": path,
                "candidate_count": count,
                "export_date": batch_ts.date() if batch_ts else None,
                "created_display": display,
            }
        )
        if len(batches) >= limit:
            break
    return batches


def _norm_name(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _load_export_index(batch: str) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Return (by_email, by_name) indexes for one export batch."""
    csv_path = EXPORTS_ROOT / batch / "candidates.csv"
    if not csv_path.is_file():
        return {}, {}
    by_email: dict[str, dict[str, str]] = {}
    by_name: dict[str, dict[str, str]] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                meta = {
                    "name": (row.get("name") or "").strip(),
                    "email": (row.get("email") or "").strip(),
                    "phone": (row.get("phone") or "").strip(),
                    "project_name": (row.get("project_name") or "").strip(),
                    "exported_at": (row.get("exported_at") or "").strip(),
                    "export_batch": batch,
                }
                email = normalize_email(row.get("email") or "")
                if email:
                    by_email[email] = meta
                name_key = _norm_name(row.get("name"))
                if name_key:
                    by_name[name_key] = meta
    except OSError as exc:
        logger.warning("Could not read export %s: %s", batch, exc)
    return by_email, by_name


def _annotate_from_export(candidate: dict, export_meta: dict[str, str]) -> dict:
    annotated = dict(candidate)
    annotated["export_batch"] = export_meta.get("export_batch") or annotated.get("export_batch")
    annotated["exported_at"] = export_meta.get("exported_at") or annotated.get("exported_at")
    annotated["_export_project_name"] = export_meta.get("project_name") or ""
    # Prefer live contact from the ZipRecruiter export when dashboard fields are empty.
    if not (annotated.get("email") or "").strip() and export_meta.get("email"):
        annotated["email"] = export_meta["email"]
    if not (annotated.get("phone") or "").strip() and export_meta.get("phone"):
        annotated["phone"] = export_meta["phone"]
    if not (annotated.get("market") or "").strip() and export_meta.get("project_name"):
        annotated["market"] = export_meta["project_name"]
    return annotated


def _match_candidates_to_batch(candidates: list[dict], batch: str) -> list[dict]:
    by_email, by_name = _load_export_index(batch)
    if not by_email and not by_name:
        return []
    matched: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        cid = candidate.get("id")
        if not cid or cid in seen:
            continue
        email = normalize_email(candidate.get("email") or "")
        meta = by_email.get(email) if email else None
        if meta is None:
            meta = by_name.get(_norm_name(candidate.get("full_name")))
        if meta is None:
            continue
        seen.add(cid)
        matched.append(_annotate_from_export(candidate, meta))
    return matched


def list_export_batches_from_candidates(candidates: list[dict]) -> list[str]:
    """Prefer DB batch values; fall back to local export folders."""
    batches: set[str] = set()
    for candidate in candidates:
        batch = (candidate.get("export_batch") or "").strip()
        if batch:
            batches.add(batch)
    if batches:
        return sorted(batches, reverse=True)
    return [b["batch"] for b in list_local_export_batches()]


def list_import_batches_from_candidates(candidates: list[dict]) -> list[str]:
    batches = {
        (c.get("import_batch") or "").strip()
        for c in candidates
        if (c.get("import_batch") or "").strip()
    }
    return sorted(batches, reverse=True)


def filter_candidates_by_export_batch(
    candidates: list[dict],
    *,
    export_batch: str | None,
) -> list[dict]:
    """Filter Pipeline list by ZR export batch (DB field or local export email match)."""
    batch = (export_batch or "").strip() or None
    if not batch:
        return list(candidates)
    return filter_candidates_for_scored_export(
        candidates, export_batch=batch, scored_only=False
    )


def filter_candidates_by_import_batch(
    candidates: list[dict],
    *,
    import_batch: str | None,
) -> list[dict]:
    batch = (import_batch or "").strip() or None
    if not batch:
        return list(candidates)
    return [
        c for c in candidates if (c.get("import_batch") or "").strip() == batch
    ]


def candidate_export_date_ct(candidate: dict) -> date | None:
    ts = resolve_export_datetime(candidate)
    if ts is None:
        return None
    local = ts.astimezone(CHICAGO) if ts.tzinfo else ts.replace(tzinfo=CHICAGO)
    return local.date()


def filter_candidates_for_scored_export(
    candidates: list[dict],
    *,
    export_batch: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    scored_only: bool = False,
) -> list[dict]:
    """Filter by ZipRecruiter export batch and/or export date range (Central Time).

    Uses candidates.export_batch when present; otherwise matches emails against
    local slack-zr-agent/exports CSVs.
    """
    batch = (export_batch or "").strip() or None
    rows: list[dict]

    if batch:
        db_hits = [
            c
            for c in candidates
            if (c.get("export_batch") or "").strip() == batch
        ]
        rows = db_hits if db_hits else _match_candidates_to_batch(candidates, batch)
    elif start_date is not None or end_date is not None:
        # Collect candidates from local batches in the date window, plus any DB matches.
        local_batches = list_local_export_batches(limit=80)
        wanted = [
            b["batch"]
            for b in local_batches
            if b.get("export_date") is not None
            and (start_date is None or b["export_date"] >= start_date)
            and (end_date is None or b["export_date"] <= end_date)
        ]
        by_id: dict[str, dict] = {}
        for wanted_batch in wanted:
            for matched in _match_candidates_to_batch(candidates, wanted_batch):
                by_id[matched["id"]] = matched
        for candidate in candidates:
            export_day = candidate_export_date_ct(candidate)
            if export_day is None:
                continue
            if start_date is not None and export_day < start_date:
                continue
            if end_date is not None and export_day > end_date:
                continue
            by_id[candidate["id"]] = candidate
        rows = list(by_id.values())
    else:
        rows = list(candidates)

    if scored_only:
        rows = [c for c in rows if parse_agent_score(c) is not None]
    return rows


def scored_export_rows(
    candidates: list[dict],
    *,
    stage_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    labels = stage_labels or {}
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        score = parse_agent_score(candidate)
        rec = parse_agent_recommendation(candidate)
        stage = candidate.get("pipeline_stage") or ""
        rows.append(
            {
                "name": candidate.get("full_name") or "",
                "email": candidate.get("email") or "",
                "phone": candidate.get("phone") or "",
                "market": candidate.get("market") or "",
                "score": score if score is not None else "",
                "recommendation": rec or "",
                "stage": labels.get(stage, stage),
                "export_batch": candidate.get("export_batch") or "",
                "exported_at": format_exported_display(candidate),
                "source": candidate.get("source") or "",
                "pipeline_stage": stage,
                "project_name": candidate.get("_export_project_name")
                or candidate.get("market")
                or "",
            }
        )
    rows.sort(
        key=lambda row: (
            -(row["score"] if isinstance(row["score"], int) else -1),
            str(row["name"]).lower(),
        )
    )
    return rows


def scored_export_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    return buffer.getvalue().encode("utf-8")


def default_export_filename(
    *,
    export_batch: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    if export_batch:
        return f"pipeline-scores-{export_batch}.csv"
    if start_date and end_date and start_date == end_date:
        return f"pipeline-scores-{start_date.isoformat()}.csv"
    if start_date and end_date:
        return f"pipeline-scores-{start_date.isoformat()}_to_{end_date.isoformat()}.csv"
    if start_date:
        return f"pipeline-scores-from-{start_date.isoformat()}.csv"
    stamp = datetime.now(CHICAGO).strftime("%Y-%m-%d_%H%M")
    return f"pipeline-scores-{stamp}.csv"
