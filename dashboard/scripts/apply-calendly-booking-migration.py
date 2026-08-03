#!/usr/bin/env python3
"""Check / print Calendly booking + Zapier RPC migration SQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
REPO = DASHBOARD.parent
MIGRATION = REPO / "supabase/migrations/20260803180000_calendly_r1_booking.sql"
RPC_MIGRATION = REPO / "supabase/migrations/20260803183000_calendly_zapier_rpcs.sql"

load_dotenv(DASHBOARD / ".env")


def main() -> int:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    columns_ok = False
    try:
        sb.table("candidates").select("r1_scheduled_at,calendly_invitee_uri").limit(1).execute()
        columns_ok = True
        print("Calendly booking columns: OK")
    except Exception:
        print("Calendly booking columns: MISSING")
        print(f"\nRun in Supabase SQL editor:\n  {MIGRATION}\n")
        print("--- columns SQL ---")
        print(MIGRATION.read_text())
        print("--- end ---")

    rpc_ok = False
    try:
        # PostgREST exposes RPCs; a bad call still proves the function exists vs 404
        sb.rpc(
            "apply_calendly_booking",
            {
                "p_email": "__zapier_probe_nonexistent__",
                "p_start_time": "2099-01-01T00:00:00Z",
            },
        ).execute()
        rpc_ok = True
        print("Zapier RPC apply_calendly_booking: OK")
    except Exception as exc:
        msg = str(exc).lower()
        if "could not find the function" in msg or "pgrst202" in msg or "404" in msg:
            print("Zapier RPC apply_calendly_booking: MISSING")
            print(f"\nRun in Supabase SQL editor:\n  {RPC_MIGRATION}\n")
            print("--- RPC SQL ---")
            print(RPC_MIGRATION.read_text())
            print("--- end ---")
        else:
            # Function exists; probe email not found is fine
            rpc_ok = True
            print(f"Zapier RPC apply_calendly_booking: OK ({type(exc).__name__})")

    print("\nZapier setup: integrations/calendly-zapier.md")
    return 0 if columns_ok and rpc_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
