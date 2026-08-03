#!/usr/bin/env python3
"""Check / print Calendly R1 booking migration SQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
REPO = DASHBOARD.parent
MIGRATION = REPO / "supabase/migrations/20260803180000_calendly_r1_booking.sql"

load_dotenv(DASHBOARD / ".env")


def main() -> int:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    try:
        sb.table("candidates").select("r1_scheduled_at,calendly_invitee_uri").limit(1).execute()
        print("Calendly booking columns already present.")
        return 0
    except Exception:
        pass

    print(
        "Columns not present yet.\n\n"
        "Run this SQL in the Supabase SQL editor:\n"
        f"  {MIGRATION}\n"
    )
    print("--- SQL ---")
    print(MIGRATION.read_text())
    print("--- end ---")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
