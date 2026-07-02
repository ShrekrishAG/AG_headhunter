#!/usr/bin/env python3
"""Score candidates missing agent pre-screens (requires OPENAI_API_KEY)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from lib.agent_prescreen_runner import prescreen_all  # noqa: E402
from lib.constants import ROLE_SLUG  # noqa: E402

load_dotenv(DASHBOARD / ".env")


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("*")
        .eq("role_id", role_id)
        .execute()
        .data
    )

    print(f"Checking {len(rows)} candidate(s) for missing agent scores…")
    done, still = prescreen_all(rows)
    print(f"Prescreen complete — {done} scored, {still} still unscored")
    return 1 if still else 0


if __name__ == "__main__":
    raise SystemExit(main())
