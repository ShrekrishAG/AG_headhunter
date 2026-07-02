#!/usr/bin/env python3
"""Backfill candidates.email and candidates.phone from inbox PDFs and profile.md."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
INBOX = ROOT / "imports" / "inbox"
CANDIDATES_DIR = ROOT / "candidates" / "sales-representative"
sys.path.insert(0, str(DASHBOARD))

from lib.resume_slug import full_name_to_resume_slug  # noqa: E402
from lib.email_utils import extract_email_from_text, normalize_email  # noqa: E402
from lib.phone_utils import extract_phone_from_text, normalize_phone_us  # noqa: E402

load_dotenv(DASHBOARD / ".env")
ROLE_SLUG = "sales-representative"


@dataclass
class ContactHints:
    email: str | None = None
    phone: str | None = None
    sources: list[str] = field(default_factory=list)


def pdftotext(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["pdftotext", str(path), "-"],
            text=True,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def contacts_from_text(text: str, source: str, hints: ContactHints) -> None:
    if not text.strip():
        return
    if not hints.email:
        email = extract_email_from_text(text)
        if email:
            hints.email = email
            hints.sources.append(f"email:{source}")
    if not hints.phone:
        phone = extract_phone_from_text(text)
        if phone:
            hints.phone = phone
            hints.sources.append(f"phone:{source}")


def contacts_from_profile(path: Path, hints: ContactHints) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    contacts_from_text(text, path.name, hints)


def contacts_for_slug(slug: str) -> ContactHints:
    hints = ContactHints()
    from lib.constants import RESUME_ROLE_PREFIX

    pdfs = sorted(INBOX.rglob(f"*-{RESUME_ROLE_PREFIX}-{slug}.pdf"))
    for pdf in pdfs:
        contacts_from_text(pdftotext(pdf), pdf.relative_to(ROOT).as_posix(), hints)
        if hints.email and hints.phone:
            break
    contacts_from_profile(CANDIDATES_DIR / slug / "profile.md", hints)
    return hints


def should_update_email(current: str | None, new: str | None) -> bool:
    if not new:
        return False
    if not current or not str(current).strip():
        return True
    return normalize_email(current) is None and normalize_email(new) is not None


def should_update_phone(current: str | None, new: str | None) -> bool:
    if not new:
        return False
    if not current or not str(current).strip():
        return True
    return normalize_phone_us(current) is None and normalize_phone_us(new) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill candidate email/phone from repo sources")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write to Supabase")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in dashboard/.env", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    candidates = (
        sb.table("candidates")
        .select("id, full_name, email, phone")
        .eq("role_id", role_id)
        .order("full_name")
        .execute()
        .data
    )

    updated_email = 0
    updated_phone = 0
    missing_email: list[str] = []
    missing_phone: list[str] = []
    missing_both: list[str] = []

    for c in candidates:
        slug = full_name_to_resume_slug(c["full_name"])
        hints = contacts_for_slug(slug)
        patch: dict[str, str] = {}

        if should_update_email(c.get("email"), hints.email):
            patch["email"] = hints.email  # type: ignore[assignment]
        if should_update_phone(c.get("phone"), hints.phone):
            patch["phone"] = hints.phone  # type: ignore[assignment]

        if patch:
            src = ", ".join(hints.sources) or "unknown"
            parts = []
            if "email" in patch:
                parts.append(f"email={patch['email']}")
            if "phone" in patch:
                parts.append(f"phone={patch['phone']}")
            print(f"{'[dry-run] ' if args.dry_run else ''}{c['full_name']}: {', '.join(parts)}  ({src})")
            if not args.dry_run:
                sb.table("candidates").update(patch).eq("id", c["id"]).execute()
            if "email" in patch:
                updated_email += 1
            if "phone" in patch:
                updated_phone += 1

        final_email = patch.get("email") or c.get("email")
        final_phone = patch.get("phone") or c.get("phone")
        if not final_email:
            missing_email.append(c["full_name"])
        if not final_phone:
            missing_phone.append(c["full_name"])
        if not final_email and not final_phone:
            missing_both.append(c["full_name"])

    with_email = len(candidates) - len(missing_email)
    with_phone = len(candidates) - len(missing_phone)

    print()
    print(f"Candidates total: {len(candidates)}")
    print(f"Updated email: {updated_email}")
    print(f"Updated phone: {updated_phone}")
    print(f"With email: {with_email}/{len(candidates)}")
    print(f"With phone: {with_phone}/{len(candidates)}")
    if missing_email:
        print(f"Missing email ({len(missing_email)}): {', '.join(missing_email)}")
    if missing_phone:
        print(f"Missing phone ({len(missing_phone)}): {', '.join(missing_phone)}")
    if missing_both:
        print(f"Missing both ({len(missing_both)}): {', '.join(missing_both)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
