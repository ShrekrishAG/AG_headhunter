#!/usr/bin/env python3
"""Full candidate sync: inbox → prescreen → uploads → ranking/stages.

Run this for every "sync candidates" / "sync applicants" request.
Always ends with agent stage + ranking sync so Pipeline metrics stay current.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
SCRIPTS = DASHBOARD / "scripts"
sys.path.insert(0, str(DASHBOARD))

load_dotenv(DASHBOARD / ".env")

from lib.agent_prescreen import parse_agent_score, parse_agent_recommendation, sort_by_agent_score  # noqa: E402
from lib.agent_prescreen_runner import prescreen_all  # noqa: E402
from lib.constants import ROLE_SLUG  # noqa: E402


def run_script(name: str, *extra: str) -> int:
    path = SCRIPTS / name
    print(f"\n── {name} {' '.join(extra)}".rstrip(), flush=True)
    result = subprocess.run([sys.executable, str(path), *extra], cwd=str(DASHBOARD))
    return result.returncode


def print_ranking_summary() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return
    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("full_name, pipeline_stage, notes")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    qualified = [r for r in rows if r["pipeline_stage"] == "qualified"]
    identified = [r for r in rows if r["pipeline_stage"] == "identified"]
    unscored = [r for r in rows if parse_agent_score(r) is None]

    print("\n══ Ranking summary ══", flush=True)
    print(
        f"Total {len(rows)} · Agent qualified {len(qualified)} · "
        f"Agent pass {len(identified)} · Unscored {len(unscored)}",
        flush=True,
    )
    if qualified:
        print("Top qualified:", flush=True)
        for r in sort_by_agent_score(qualified)[:8]:
            score = parse_agent_score(r)
            rec = parse_agent_recommendation(r)
            score_txt = f"{score}/100" if score is not None else "—"
            print(f"  {score_txt:8} {rec or '—':20} {r['full_name']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Full candidate sync pipeline")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--skip-prescreen",
        action="store_true",
        help="Skip AI prescreen (stages still sync from existing profiles)",
    )
    parser.add_argument(
        "--skip-uploads",
        action="store_true",
        help="Skip resume upload + avatar sync",
    )
    parser.add_argument(
        "--skip-drafts",
        action="store_true",
        help="Skip reference outreach draft generation",
    )
    args = parser.parse_args()

    steps_failed = 0

    code = run_script("process-inbox.py", "--date", args.date)
    if code:
        steps_failed += 1

    if not args.skip_prescreen:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            sb = create_client(url, key)
            role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
            rows = (
                sb.table("candidates").select("*").eq("role_id", role_id).execute().data
            )
            print("\n── agent prescreen (unscored)", flush=True)
            done, still = prescreen_all(rows)
            print(f"Prescreen — {done} scored, {still} still unscored", flush=True)
            if still and not os.getenv("OPENAI_API_KEY"):
                print("Set OPENAI_API_KEY in dashboard/.env for automatic prescreen.", flush=True)
        else:
            code = run_script("agent-prescreen-unscored.py")
            if code:
                steps_failed += 1

    if not args.skip_uploads:
        for script in ("upload-resumes.py", "sync-avatars.py", "backfill-candidate-contacts.py"):
            code = run_script(script)
            if code:
                steps_failed += 1

    # Always refresh pipeline stages + notes from profile scores (ranking source).
    code = run_script("sync-agent-stages.py")
    if code:
        steps_failed += 1

    if not args.skip_drafts and os.environ.get("GENERATE_OUTREACH_DRAFTS", "true").lower() in (
        "1",
        "true",
        "yes",
    ):
        code = run_script("generate-outreach-drafts.py")
        if code:
            steps_failed += 1

    print_ranking_summary()

    if steps_failed:
        print(f"\nSync finished with {steps_failed} step(s) reporting errors.", flush=True)
        return 1
    print("\nSync complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
