#!/usr/bin/env python3
"""Insert Sample cand duplicates (same phone/email) for bulk SMS/email testing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EMAIL = "shreya@dollfamilyoffice.com"
PHONE = "+14085150245"
NOTES = "Resume pre-screen 2026-06-30 · 100/100 · Strong interview · Bulk outreach test duplicate"

DUPLICATES = [
    {
        "full_name": "Sample cand B",
        "current_title": "Project Sales Consultant",
        "current_company": "Accord Test Profile",
        "source": "Test sample",
        "market": "TGC - KC, MO",
        "pipeline_stage": "qualified",
    },
    {
        "full_name": "Sample cand C",
        "current_title": "Project Sales Consultant",
        "current_company": "Accord Test Profile",
        "source": "Test sample",
        "market": "TGC - KC, MO",
        "pipeline_stage": "qualified",
    },
    {
        "full_name": "Sample cand D",
        "current_title": "Project Sales Consultant",
        "current_company": "Accord Test Profile",
        "source": "Test sample",
        "market": "TGC - KC, MO",
        "pipeline_stage": "qualified",
    },
]


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", "sales-representative").execute().data[0]["id"]
    existing = (
        sb.table("candidates")
        .select("full_name")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    existing_names = {row["full_name"] for row in existing}

    inserted = skipped = 0
    for row in DUPLICATES:
        if row["full_name"] in existing_names:
            print(f"Skip (exists): {row['full_name']}")
            skipped += 1
            continue
        payload = {
            "role_id": role_id,
            "email": EMAIL,
            "phone": PHONE,
            "notes": NOTES,
            **row,
        }
        sb.table("candidates").insert(payload).execute()
        print(f"Inserted: {row['full_name']} · {EMAIL} · {PHONE}")
        inserted += 1

    print(f"Done — {inserted} inserted, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
