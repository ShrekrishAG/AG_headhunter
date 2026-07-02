#!/usr/bin/env python3
"""Upload inbox PDFs to Supabase Storage and set candidates.resume_url."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "imports" / "inbox"
DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from lib.resume_slug import full_name_to_resume_slug  # noqa: E402

load_dotenv(DASHBOARD / ".env")

BUCKET = "resumes"
ROLE_SLUG = "sales-representative"


def _public_url(sb, storage_path: str) -> str:
    return sb.storage.from_(BUCKET).get_public_url(storage_path)


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1

    from lib.constants import RESUME_ROLE_PREFIX

    pdfs = sorted(INBOX.rglob(f"*-{RESUME_ROLE_PREFIX}-*.pdf"))
    if not pdfs:
        print(f"No resume PDFs found in {INBOX}")
        return 0

    sb = create_client(url, key)
    role_id = (
        sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    )
    candidates = (
        sb.table("candidates")
        .select("id, full_name, resume_url")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    by_slug = {full_name_to_resume_slug(c["full_name"]): c for c in candidates}

    uploaded = 0
    for pdf in pdfs:
        match = re.search(rf"{RESUME_ROLE_PREFIX}-([a-z]+-[a-z]+)\.pdf$", pdf.name, re.I)
        if not match:
            print(f"Skip (name pattern): {pdf.name}")
            continue
        slug = match.group(1).lower()
        candidate = by_slug.get(slug)
        if not candidate:
            print(f"Skip (no candidate for slug {slug}): {pdf.name}")
            continue

        storage_path = f"{ROLE_SLUG}/{slug}.pdf"
        with pdf.open("rb") as handle:
            sb.storage.from_(BUCKET).upload(
                storage_path,
                handle.read(),
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true",
                },
            )
        resume_url = _public_url(sb, storage_path)
        sb.table("candidates").update({"resume_url": resume_url}).eq(
            "id", candidate["id"]
        ).execute()
        print(f"Uploaded {pdf.name} -> {candidate['full_name']}")
        uploaded += 1

    print(f"Done — {uploaded} resume(s) uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
