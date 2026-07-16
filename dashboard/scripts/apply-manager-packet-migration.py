#!/usr/bin/env python3
"""Check / print manager packet send-log migration SQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
REPO = DASHBOARD.parent
MIGRATION = REPO / "supabase/migrations/20260716120000_manager_packet_sends.sql"

load_dotenv(DASHBOARD / ".env")


def main() -> int:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    try:
        sb.table("manager_packet_sends").select("id").limit(1).execute()
        print("manager_packet_sends is already enabled.")
        return 0
    except Exception:
        pass

    print(
        "Table not present yet.\n\n"
        "Run this SQL in the Supabase SQL editor:\n"
        f"  {MIGRATION}\n"
    )
    print("--- SQL ---")
    print(MIGRATION.read_text())
    print("--- end ---")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
