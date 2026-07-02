#!/usr/bin/env python3
"""Import candidates from a slack-zr-agent ZipRecruiter export folder.

Copies resume PDFs into imports/inbox/ZipRecruiter/ with the standard naming
convention, then runs process-inbox + optional sync.

Example:
  python dashboard/scripts/import-ziprecruiter-export.py \\
    --export-dir ../slack-zr-agent/exports/2026-06-24_110147
  python dashboard/scripts/import-ziprecruiter-export.py --latest
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = Path(__file__).resolve().parents[1]
INBOX_ZR = ROOT / "imports" / "inbox" / "ZipRecruiter"
DEFAULT_EXPORTS = ROOT.parent / "slack-zr-agent" / "exports"
sys.path.insert(0, str(DASHBOARD))

from lib.constants import RESUME_ROLE_PREFIX  # noqa: E402
from lib.resume_slug import full_name_to_resume_slug  # noqa: E402


def find_latest_export(exports_root: Path) -> Path | None:
    if not exports_root.is_dir():
        return None
    dirs = sorted(
        (p for p in exports_root.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


def load_manifest(export_dir: Path) -> list[dict]:
    csv_path = export_dir / "candidates.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"No candidates.csv in {export_dir}")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def copy_resumes(export_dir: Path, import_date: str) -> tuple[int, int, list[dict]]:
    INBOX_ZR.mkdir(parents=True, exist_ok=True)
    copied = refreshed = 0
    metadata: list[dict] = []

    for row in load_manifest(export_dir):
        resume_file = (row.get("resume_filename") or "").strip()
        name = (row.get("name") or "").strip()
        if not name:
            continue

        slug = full_name_to_resume_slug(name)
        dest_name = f"{import_date}-{RESUME_ROLE_PREFIX}-{slug}.pdf"
        dest = INBOX_ZR / dest_name

        meta = {
            "full_name": name,
            "email": (row.get("email") or "").strip() or None,
            "phone": (row.get("phone") or "").strip() or None,
            "market": (row.get("project_name") or "").strip() or None,
            "ziprecruiter_project_id": (row.get("project_id") or "").strip() or None,
            "source": "ZipRecruiter",
            "slug": slug,
            "resume_filename": dest_name,
        }
        metadata.append(meta)

        if not resume_file:
            print(f"  No resume file for {name} — profile only", flush=True)
            continue

        src = export_dir / "resumes" / resume_file
        if not src.is_file():
            src = export_dir / resume_file
        if not src.is_file():
            print(f"  Missing PDF for {name}: {resume_file}", flush=True)
            continue

        existed = dest.exists()
        shutil.copy2(src, dest)
        if existed:
            refreshed += 1
            print(f"  Refreshed: {name} → {dest_name}", flush=True)
        else:
            copied += 1
            print(f"  Copied: {name} → {dest_name}", flush=True)

    manifest_path = INBOX_ZR / f"{import_date}-zr-manifest.json"
    manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return copied, refreshed, metadata


def apply_manifest_to_inbox(manifest: list[dict], import_date: str) -> None:
    """Write sidecar JSON next to each resume for process-inbox enrichment."""
    for row in manifest:
        sidecar = INBOX_ZR / f"{import_date}-{RESUME_ROLE_PREFIX}-{row['slug']}.json"
        sidecar.write_text(json.dumps(row, indent=2), encoding="utf-8")


def run_process_inbox() -> int:
    script = DASHBOARD / "scripts" / "process-inbox.py"
    return subprocess.call([sys.executable, str(script), "--date", date.today().isoformat()])


def enrich_from_sidecars() -> int:
    """Patch Supabase rows with market/email/phone from ZipRecruiter sidecars."""
    import os

    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(DASHBOARD / ".env")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Skip enrichment — SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
        return 0

    sb = create_client(url, key)
    role_id = (
        sb.table("roles").select("id").eq("slug", "sales-representative").execute().data[0]["id"]
    )
    updated = 0
    for sidecar in INBOX_ZR.glob(f"*-{RESUME_ROLE_PREFIX}-*.json"):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        slug = data.get("slug")
        if not slug:
            continue
        rows = (
            sb.table("candidates")
            .select("id, full_name, email, phone, market")
            .eq("role_id", role_id)
            .execute()
            .data
        )
        match = next(
            (r for r in rows if full_name_to_resume_slug(r["full_name"]) == slug),
            None,
        )
        if not match:
            continue
        patch = {}
        for field in ("email", "phone", "market", "ziprecruiter_project_id"):
            if data.get(field):
                patch[field] = data[field]
        if patch:
            sb.table("candidates").update(patch).eq("id", match["id"]).execute()
            updated += 1
            print(f"  Enriched: {match['full_name']}", flush=True)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Import ZipRecruiter export")
    parser.add_argument("--export-dir", type=Path, help="Path to export folder")
    parser.add_argument(
        "--exports-root",
        type=Path,
        default=DEFAULT_EXPORTS,
        help="Root folder containing dated exports (for --latest)",
    )
    parser.add_argument("--latest", action="store_true", help="Use newest export folder")
    parser.add_argument("--copy-only", action="store_true", help="Only copy PDFs, do not sync")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    export_dir = args.export_dir
    if args.latest or export_dir is None:
        export_dir = find_latest_export(args.exports_root)
        if not export_dir:
            print(f"No exports found under {args.exports_root}", file=sys.stderr)
            return 1

    if not export_dir.is_dir():
        print(f"Export dir not found: {export_dir}", file=sys.stderr)
        return 1

    print(f"Importing from {export_dir}", flush=True)
    copied, refreshed, manifest = copy_resumes(export_dir, args.date)
    apply_manifest_to_inbox(manifest, args.date)
    print(f"Done — {copied} copied, {refreshed} refreshed", flush=True)

    if args.copy_only:
        return 0

    code = run_process_inbox()
    if code != 0:
        return code
    enrich_from_sidecars()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
