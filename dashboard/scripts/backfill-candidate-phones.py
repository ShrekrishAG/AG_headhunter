#!/usr/bin/env python3
"""Extract phone numbers from inbox resume PDFs into candidates.phone.

Deprecated: use backfill-candidate-contacts.py for email + phone backfill.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
INBOX = ROOT / "imports" / "inbox"
sys.path.insert(0, str(DASHBOARD))

from lib.candidate_display import full_name_to_resume_slug  # noqa: E402
from lib.phone_utils import extract_phone_from_text  # noqa: E402

load_dotenv(DASHBOARD / ".env")
ROLE_SLUG = "sales-representative"


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    candidates = (
        sb.table("candidates")
        .select("id, full_name, phone, email")
        .eq("role_id", role_id)
        .execute()
        .data
    )

    updated = 0
    for c in candidates:
        if c.get("phone"):
            continue
        slug = full_name_to_resume_slug(c["full_name"])
        from lib.constants import RESUME_ROLE_PREFIX

        pdfs = sorted(INBOX.rglob(f"*-{RESUME_ROLE_PREFIX}-{slug}.pdf"))
        phone = None
        for pdf in pdfs:
            try:
                text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True, errors="replace")
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
            phone = extract_phone_from_text(text)
            if phone:
                break
        if phone:
            sb.table("candidates").update({"phone": phone}).eq("id", c["id"]).execute()
            print(f"Phone: {c['full_name']} -> {phone}")
            updated += 1

    print(f"Done — {updated} phone(s) backfilled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
