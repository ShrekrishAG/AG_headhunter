#!/usr/bin/env python3
"""One-time sync: insert resume-import candidates into Supabase."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CANDIDATES = [
    {
        "full_name": "Zachery Huffman",
        "email": "zhuffman96@gmail.com",
        "linkedin_url": "https://www.linkedin.com/in/zachery-huffman-76bb3215a/",
        "current_title": "Account Manager II, Direct Sales",
        "current_company": "Vendasta (Broadly)",
        "source": "Other",
        "pipeline_stage": "qualified",
        "notes": "Resume pre-screen 2026-06-23 · 3.60 · Recommend · Priority #1",
    },
    {
        "full_name": "Casey Copeland",
        "email": "ccopeland01@gmail.com",
        "linkedin_url": None,
        "current_title": "Chief Marketing Officer",
        "current_company": "Mid America Capital",
        "source": "Other",
        "pipeline_stage": "qualified",
        "notes": "Resume pre-screen 2026-06-23 · 3.35 · Consider · Priority #2",
    },
    {
        "full_name": "Zach Stegenga",
        "email": "zstegenga@gmail.com",
        "linkedin_url": None,
        "current_title": "Vice President, Origination",
        "current_company": "Grey Fox Partners",
        "source": "Other",
        "pipeline_stage": "identified",
        "notes": "Resume pre-screen 2026-06-23 · 2.45 · Pass — PE origination",
    },
    {
        "full_name": "John Carr",
        "email": "jtcarr15@gmail.com",
        "linkedin_url": "https://www.linkedin.com/in/johnthomascarr",
        "current_title": "Assistant Vice President, Operational Implementations",
        "current_company": "SWBC",
        "source": "Other",
        "pipeline_stage": "identified",
        "notes": "Resume pre-screen 2026-06-23 · 2.35 · Pass — finserv implementations",
    },
    {
        "full_name": "Cody Danuser",
        "email": "danusers@outlook.com",
        "linkedin_url": "https://www.linkedin.com/in/codydanuser",
        "current_title": "President & CEO",
        "current_company": "Express Medical Transportation",
        "source": "Other",
        "pipeline_stage": "identified",
        "notes": "Resume pre-screen 2026-06-23 · 2.40 · Pass — healthcare EMS",
    },
]


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    roles = sb.table("roles").select("id, slug").eq("slug", "sales-representative").execute().data
    if not roles:
        print("Role sales-representative not found — run migration first.", file=sys.stderr)
        return 1

    role_id = roles[0]["id"]
    existing = (
        sb.table("candidates")
        .select("full_name")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    existing_names = {r["full_name"] for r in existing}

    inserted = 0
    skipped = 0
    for row in CANDIDATES:
        if row["full_name"] in existing_names:
            print(f"Skip (exists): {row['full_name']}")
            skipped += 1
            continue
        payload = {"role_id": role_id, **row}
        sb.table("candidates").insert(payload).execute()
        print(f"Inserted: {row['full_name']}")
        inserted += 1

    print(f"Done — {inserted} inserted, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
