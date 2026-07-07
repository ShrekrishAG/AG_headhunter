#!/usr/bin/env python3
"""Backfill candidates.exported_at and export_batch from slack-zr-agent exports."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
EXPORTS = ROOT / "slack-zr-agent" / "exports"
sys.path.insert(0, str(DASHBOARD))

from lib.constants import ROLE_SLUG  # noqa: E402
from lib.export_display import parse_export_batch, parse_export_timestamp  # noqa: E402
from lib.resume_slug import full_name_to_resume_slug  # noqa: E402

load_dotenv(DASHBOARD / ".env")


def _export_dirs(exports_root: Path) -> list[Path]:
    if not exports_root.is_dir():
        return []
    return sorted(
        (p for p in exports_root.iterdir() if p.is_dir() and (p / "candidates.csv").is_file()),
        key=lambda p: p.name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ZipRecruiter export metadata")
    parser.add_argument("--exports-root", type=Path, default=EXPORTS)
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    try:
        sb.table("candidates").select("exported_at, export_batch").limit(1).execute()
    except Exception as exc:
        print(
            "Export columns missing — apply migration first:\n"
            "  supabase/migrations/20260706120000_candidate_export_tracking.sql\n"
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1

    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("id, full_name")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    by_slug = {full_name_to_resume_slug(r["full_name"]): r for r in rows}

    updated = 0
    for export_dir in _export_dirs(args.exports_root):
        batch = export_dir.name
        batch_ts = parse_export_batch(batch)
        with (export_dir / "candidates.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                match = by_slug.get(full_name_to_resume_slug(name))
                if not match:
                    continue
                exported_at = parse_export_timestamp((row.get("exported_at") or "").strip())
                payload = {"export_batch": batch}
                if exported_at is not None:
                    payload["exported_at"] = exported_at.isoformat()
                elif batch_ts is not None:
                    payload["exported_at"] = batch_ts.isoformat()
                sb.table("candidates").update(payload).eq("id", match["id"]).execute()
                updated += 1

    print(f"Backfill complete — {updated} candidate row update(s) from exports", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
