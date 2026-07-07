"""Gate resume qualification on ZipRecruiter export batch date."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from lib.constants import DASHBOARD_ROOT
from lib.export_display import parse_export_batch

MIN_QUALIFYING_EXPORT_DATE = date(2026, 7, 6)
EXPORTS_ROOT = DASHBOARD_ROOT.parent / "slack-zr-agent" / "exports"


def _export_dirs(exports_root: Path) -> list[Path]:
    if not exports_root.is_dir():
        return []
    return sorted(
        (p for p in exports_root.iterdir() if p.is_dir() and (p / "candidates.csv").is_file()),
        key=lambda p: p.name,
    )


def build_earliest_export_by_email(exports_root: Path = EXPORTS_ROOT) -> dict[str, date]:
    """Map normalized email -> earliest local export batch date."""
    index: dict[str, date] = {}
    for export_dir in _export_dirs(exports_root):
        batch = export_dir.name
        batch_ts = parse_export_batch(batch)
        if batch_ts is None:
            continue
        batch_date = batch_ts.date()
        with (export_dir / "candidates.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                email = (row.get("email") or "").strip().lower()
                if not email:
                    continue
                if email not in index or batch_date < index[email]:
                    index[email] = batch_date
    return index


def candidate_export_date(
    candidate: dict,
    *,
    earliest_by_email: dict[str, date] | None = None,
) -> date | None:
    email = (candidate.get("email") or "").strip().lower()
    if email and earliest_by_email and email in earliest_by_email:
        return earliest_by_email[email]

    batch = (candidate.get("export_batch") or "").strip()
    batch_ts = parse_export_batch(batch)
    if batch_ts is not None:
        return batch_ts.date()

    exported_at = candidate.get("exported_at")
    if exported_at:
        try:
            from datetime import datetime

            return datetime.fromisoformat(str(exported_at).replace("Z", "+00:00")).date()
        except ValueError:
            pass

    created = (candidate.get("created_at") or "")[:10]
    if created:
        try:
            return date.fromisoformat(created)
        except ValueError:
            pass
    return None


def eligible_for_resume_qualification(
    candidate: dict,
    *,
    earliest_by_email: dict[str, date] | None = None,
) -> bool:
    export_date = candidate_export_date(candidate, earliest_by_email=earliest_by_email)
    if export_date is None:
        return True
    return export_date >= MIN_QUALIFYING_EXPORT_DATE
