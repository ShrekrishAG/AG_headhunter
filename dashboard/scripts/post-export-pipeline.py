#!/usr/bin/env python3
"""Run full post-export pipeline: import → sync → reference drafts.

Prints a machine-readable summary line for Slack integration:
  PIPELINE_SUMMARY={"imported":...}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
SCRIPTS = DASHBOARD / "scripts"
ROOT = DASHBOARD.parent
sys.path.insert(0, str(DASHBOARD))
load_dotenv(DASHBOARD / ".env")

from lib.agent_prescreen import parse_agent_recommendation, parse_agent_score  # noqa: E402
from lib.candidate_activity import is_contacted  # noqa: E402
from lib.constants import ROLE_SLUG  # noqa: E402

SUMMARY_PREFIX = "PIPELINE_SUMMARY="


def run_script(name: str, *extra: str) -> int:
    path = SCRIPTS / name
    print(f"\n── {name} {' '.join(extra)}".rstrip(), flush=True)
    return subprocess.call([sys.executable, str(path), *extra], cwd=str(DASHBOARD))


def qualified_ready_for_review(sb) -> list[dict]:
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("id, full_name, pipeline_stage, notes, sms_outreach_count, email_outreach_count")
        .eq("role_id", role_id)
        .eq("pipeline_stage", "qualified")
        .execute()
        .data
    )
    ready = []
    for row in rows:
        if is_contacted(row):
            continue
        score = parse_agent_score(row)
        rec = parse_agent_recommendation(row)
        if score is None or not rec:
            continue
        ready.append({**row, "score": score, "recommendation": rec})
    ready.sort(key=lambda r: r.get("score") or 0, reverse=True)
    return ready


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-export import and sync pipeline")
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-drafts", action="store_true")
    args = parser.parse_args()

    export_dir = args.export_dir
    if export_dir.is_absolute():
        export_dir = export_dir.resolve()
    else:
        monorepo_path = (ROOT / "slack-zr-agent" / export_dir).resolve()
        export_dir = monorepo_path if monorepo_path.is_dir() else export_dir.resolve()
    if not export_dir.is_dir():
        print(f"Export dir not found: {export_dir}", file=sys.stderr)
        return 1

    export_batch = export_dir.name
    steps_failed = 0

    code = run_script(
        "import-ziprecruiter-export.py",
        "--export-dir",
        str(export_dir),
        "--date",
        date.today().isoformat(),
    )
    if code:
        steps_failed += 1

    if not args.skip_sync:
        code = run_script("sync-candidates.py", "--skip-uploads", "--skip-drafts")
        if code:
            steps_failed += 1

    if not args.skip_drafts:
        code = run_script("generate-outreach-drafts.py", "--export-batch", export_batch)
        if code:
            steps_failed += 1

    summary = {
        "export_batch": export_batch,
        "steps_failed": steps_failed,
        "streamlit_url": os.environ.get("STREAMLIT_APP_URL", "").strip(),
        "ready": [],
    }

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        sb = create_client(url, key)
        ready = qualified_ready_for_review(sb)
        summary["ready_count"] = len(ready)
        summary["ready"] = [
            {
                "full_name": row["full_name"],
                "score": row["score"],
                "recommendation": row["recommendation"],
            }
            for row in ready[:12]
        ]
        role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
        all_rows = (
            sb.table("candidates").select("id").eq("role_id", role_id).execute().data
        )
        summary["total_candidates"] = len(all_rows)

    print(f"\n{SUMMARY_PREFIX}{json.dumps(summary)}", flush=True)
    return 1 if steps_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
