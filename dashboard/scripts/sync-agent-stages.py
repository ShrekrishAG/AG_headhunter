#!/usr/bin/env python3
"""Sync candidates.pipeline_stage and notes from profile.md agent pre-screens."""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from lib.agent_prescreen import (  # noqa: E402
    parse_agent_recommendation,
    parse_agent_score,
    profile_path_for,
)
from lib.constants import ROLE_SLUG  # noqa: E402
from lib.export_eligibility import (  # noqa: E402
    build_earliest_export_by_email,
    eligible_for_resume_qualification,
)
from lib.rubric import qualifies_for_pipeline  # noqa: E402

load_dotenv(DASHBOARD / ".env")

EARLY_STAGES = {"identified", "qualified"}


def stage_from_profile(
    candidate: dict,
    *,
    earliest_by_email: dict | None = None,
) -> str | None:
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    if score is None or not rec:
        return None
    if (
        qualifies_for_pipeline(score, rec)
        and eligible_for_resume_qualification(
            candidate, earliest_by_email=earliest_by_email
        )
    ):
        return "qualified"
    return "identified"


def notes_from_profile(candidate: dict) -> str | None:
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    if score is None or not rec:
        return None
    existing = (candidate.get("notes") or "").strip()
    prescreen_line = f"Resume pre-screen {date.today().isoformat()} · {score}/100 · {rec}"
    if re.search(r"Resume pre-screen \d{4}-\d{2}-\d{2}", existing):
        existing = re.sub(
            r"Resume pre-screen \d{4}-\d{2}-\d{2} · [^\n]+",
            prescreen_line,
            existing,
        )
    elif existing:
        existing = f"{prescreen_line}\n\n{existing}"
    else:
        existing = prescreen_line
    return existing


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    earliest_by_email = build_earliest_export_by_email()
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("id, full_name, email, created_at, pipeline_stage, notes")
        .eq("role_id", role_id)
        .execute()
        .data
    )

    updated = skipped = no_score = 0
    for row in rows:
        new_stage = stage_from_profile(row, earliest_by_email=earliest_by_email)
        if new_stage is None:
            no_score += 1
            print(f"No score: {row['full_name']}")
            continue

        payload: dict = {}
        if row["pipeline_stage"] in EARLY_STAGES:
            if row["pipeline_stage"] != new_stage:
                payload["pipeline_stage"] = new_stage
        new_notes = notes_from_profile(row)
        if new_notes and new_notes != (row.get("notes") or ""):
            payload["notes"] = new_notes

        if not payload:
            skipped += 1
            continue

        sb.table("candidates").update(payload).eq("id", row["id"]).execute()
        updated += 1
        parts = [row["full_name"]]
        if "pipeline_stage" in payload:
            parts.append(f"{row['pipeline_stage']} → {payload['pipeline_stage']}")
        if "notes" in payload:
            parts.append("notes updated")
        print(" · ".join(parts))

    print(f"\nDone — {updated} updated, {skipped} unchanged, {no_score} unscored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
