#!/usr/bin/env python3
"""Move pre–Jul 6 export candidates from qualified to identified."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from lib.constants import ROLE_SLUG  # noqa: E402
from lib.export_eligibility import (  # noqa: E402
    MIN_QUALIFYING_EXPORT_DATE,
    build_earliest_export_by_email,
    candidate_export_date,
    eligible_for_resume_qualification,
)

load_dotenv(DASHBOARD / ".env")


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
        .select("id, full_name, email, created_at, pipeline_stage")
        .eq("role_id", role_id)
        .eq("pipeline_stage", "qualified")
        .execute()
        .data
    )

    demoted = kept = 0
    for row in rows:
        export_date = candidate_export_date(row, earliest_by_email=earliest_by_email)
        if eligible_for_resume_qualification(row, earliest_by_email=earliest_by_email):
            kept += 1
            continue
        sb.table("candidates").update({"pipeline_stage": "identified"}).eq(
            "id", row["id"]
        ).execute()
        demoted += 1
        print(
            f"{row['full_name']} · qualified → identified "
            f"(first export {export_date}, cutoff {MIN_QUALIFYING_EXPORT_DATE})"
        )

    print(f"\nDone — {demoted} demoted, {kept} remain qualified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
