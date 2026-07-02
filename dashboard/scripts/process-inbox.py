#!/usr/bin/env python3
"""Process resume imports from imports/inbox/ (including source subfolders).

Renames files to YYYY-MM-DD-sales-rep-<lastname>-<firstname>.pdf,
dedupes against Supabase and candidates/, creates profile.md, and inserts rows.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "imports" / "inbox"
LAST_PROCESSED = ROOT / "imports" / ".last-processed"
DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from lib.resume_slug import full_name_to_resume_slug  # noqa: E402
from lib.constants import RESUME_ROLE_PREFIX, ROLE_SLUG, SOURCES  # noqa: E402

CANDIDATES_DIR = ROOT / "candidates" / ROLE_SLUG

load_dotenv(DASHBOARD / ".env")

RESUME_GLOB = f"*-{RESUME_ROLE_PREFIX}-*.pdf"
RESUME_RE = re.compile(
    rf"^(\d{{4}}-\d{{2}}-\d{{2}})-{RESUME_ROLE_PREFIX}-([a-z]+-[a-z]+)\.pdf$", re.I
)
INDEED_RESUME_RE = re.compile(r"^Resume(.+)\.(pdf|docx)$", re.I)

FOLDER_SOURCE = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "ziprecruiter": "ZipRecruiter",
    "personal-network": "Personal network",
    "referral": "Referral",
    "outbound": "Outbound",
    "other": "Other",
}


def _pdftotext(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout or ""
    except FileNotFoundError:
        return ""


def _docx_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout or ""
    except FileNotFoundError:
        return ""


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _pdftotext(path)
    if path.suffix.lower() == ".docx":
        return _docx_text(path)
    return ""


def _name_from_indeed_filename(name_part: str) -> str | None:
    """ResumeMichaelRudd.pdf -> Michael Rudd; ResumePetar(Peter)Krstic -> Petar Krstic."""
    cleaned = re.sub(r"\([^)]*\)", "", name_part)
    # Insert space before interior capitals: MichaelRudd -> Michael Rudd
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    cleaned = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", cleaned)
    # All-caps concatenated: RICHARDSELBY -> Richard Selby
    if cleaned.isupper() and " " not in cleaned and len(cleaned) > 6:
        for split_at in range(len(cleaned) - 2, 2, -1):
            first, last = cleaned[:split_at], cleaned[split_at:]
            if first.isalpha() and last.isalpha() and len(last) >= 3:
                cleaned = f"{first} {last}"
                break
    parts = cleaned.split()
    if not parts:
        return None
    return " ".join(p.capitalize() if p.isupper() else p for p in parts)


def _name_from_linkedin_url(url: str) -> str | None:
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url, re.I)
    if not match:
        return None
    slug = match.group(1).rstrip("/")
    slug = re.sub(r"-\d+$", "", slug)
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    if len(parts) >= 2:
        return " ".join(p.capitalize() for p in parts[:3])
    return None


def _name_from_email(email: str) -> str | None:
    local = email.split("@", 1)[0]
    parts = [p for p in re.split(r"[._+-]", local) if p and not p.isdigit()]
    if len(parts) >= 2:
        a, b = parts[0], parts[1]
        if len(a) >= len(b):
            last, first = a, b
        else:
            last, first = b, a
        first = re.sub(r"\d+$", "", first)
        return f"{first.capitalize()} {last.capitalize()}"
    return None


def _name_from_text(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()[:8] if line.strip()]
    if len(lines) >= 2:
        first, second = lines[0], lines[1]
        if (
            re.match(r"^[A-Z][A-Z.'\-]{1,18}$", first)
            and re.match(r"^[A-Z][A-Z.'\-]{2,24}$", second)
            and not re.search(r"\d", first + second)
            and "@" not in second
        ):
            return f"{first.title()} {second.title()}"

    for line in lines:
        line = line.strip()
        if not line or len(line) > 70:
            continue
        if "@" in line or re.search(r"\d{3}[-.\s]?\d{3}", line):
            continue
        # Strip parenthetical segments: Sara (Miller) Zittergruen
        line = re.sub(r"\([^)]*\)", "", line).strip()
        # "Brian M. Savoy, II" -> "Brian M. Savoy II"
        line = re.sub(r",\s*(II|III|IV|Jr\.?|Sr\.?)$", r" \1", line, flags=re.I)
        if re.match(
            r"^[A-Z][A-Za-z.'\-]*"
            r"(?:\s+[A-Z]\.?)?"
            r"(?:\s+[A-Z][A-Za-z.'\-]+){1,2}"
            r"(?:\s+(?:II|III|IV|Jr\.?|Sr\.?))?$",
            line,
            re.I,
        ):
            cleaned = " ".join(line.split())
            if cleaned.isupper():
                cleaned = cleaned.title()
                cleaned = re.sub(r"\bIi\b", "II", cleaned)
                cleaned = re.sub(r"\bIii\b", "III", cleaned)
                cleaned = re.sub(r"\bIv\b", "IV", cleaned)
            return cleaned
        if re.match(r"^[A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){1,3}$", line):
            return line.title() if line.isupper() else line
        if re.match(r"^[A-Z][A-Z\s.'\-]{3,40}$", line):
            cleaned = line.title()
            cleaned = re.sub(r"\bIi\b", "II", cleaned)
            return cleaned
    return None


def _email_from_text(text: str) -> str | None:
    from lib.email_utils import extract_email_from_text

    return extract_email_from_text(text)


def _phone_from_text(text: str) -> str | None:
    from lib.phone_utils import extract_phone_from_text

    return extract_phone_from_text(text)


def _title_company_from_text(text: str) -> tuple[str | None, str | None]:
    """Best-effort headline parse from resume body."""
    for line in text.splitlines()[1:20]:
        line = line.strip()
        if not line or len(line) > 120 or "@" in line:
            continue
        if re.search(r"\d{3}[-.\s]?\d{3}", line):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if parts:
                return parts[0], parts[1] if len(parts) > 1 else None
        if " · " in line:
            parts = [p.strip() for p in line.split(" · ") if p.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]
        if " at " in line.lower():
            idx = line.lower().index(" at ")
            return line[:idx].strip(), line[idx + 4 :].strip()
    return None, None


def write_profile_stub(
    *,
    slug: str,
    full_name: str,
    source: str,
    import_date: str,
    email: str | None = None,
    linkedin_url: str | None = None,
    current_title: str | None = None,
    current_company: str | None = None,
) -> Path:
    profile_dir = CANDIDATES_DIR / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / "profile.md"
    title_line = " · ".join(x for x in (current_title, current_company) if x) or "—"
    content = f"""# Candidate profile

**Role slug:** {ROLE_SLUG}  
**Name:** {full_name}  
**Current title / company:** {title_line}  
**LinkedIn:** {linkedin_url or "—"}  
**Source:** {source}  
**Referrer:** —  
**Stage:** Identified  
**Owner:** Accord Recruiting  
**Last updated:** {import_date}

## Summary

Pending resume pre-screen.

## Interaction log

| Date | Type | Notes |
|------|------|-------|
| {import_date} | Resume import | Added from imports/inbox/{source} |

## Next step

- Agent pre-screen
"""
    path.write_text(content, encoding="utf-8")
    return path


def _name_from_resume_slug(slug: str) -> str:
    parts = slug.split("-")
    if len(parts) >= 2:
        first = parts[-1]
        last = "-".join(parts[:-1])
        return f"{first.title()} {last.title()}"
    return slug.title()


def sync_resume_pdf(
    path: Path,
    sb,
    role_id: str,
    keys: dict,
    *,
    import_date: str,
) -> str:
    """Returns: inserted | updated | skipped | error."""
    match = RESUME_RE.match(path.name)
    if not match:
        return "skipped"
    file_date, slug = match.group(1), match.group(2).lower()

    text = _extract_text(path)
    email = _email_from_text(text)
    linkedin_url = _linkedin_from_text(text)
    if linkedin_url and not linkedin_url.startswith("http"):
        linkedin_url = "https://www.linkedin.com/in/" + linkedin_url.split("/in/")[-1].strip("/") + "/"

    full_name = _name_from_text(text)
    if not full_name and linkedin_url:
        full_name = _name_from_linkedin_url(linkedin_url)
    if not full_name and email:
        full_name = _name_from_email(email)
    if not full_name:
        full_name = _name_from_resume_slug(slug)
    elif full_name_to_resume_slug(full_name) != slug:
        full_name = _name_from_resume_slug(slug)

    source = folder_source(path)
    title, company = _title_company_from_text(text)
    phone = _phone_from_text(text)

    existing = resolve_existing_candidate(
        keys,
        slug=slug,
        email=email,
        linkedin_url=linkedin_url,
    )
    profile_path = CANDIDATES_DIR / slug / "profile.md"

    if existing:
        patch: dict = {}
        for field, value in (
            ("email", email),
            ("phone", phone),
            ("linkedin_url", linkedin_url),
            ("current_title", title),
            ("current_company", company),
            ("full_name", full_name),
        ):
            if value and existing.get(field) != value:
                patch[field] = value
        rel_path = str(path.relative_to(INBOX))
        reimport_note = f"Resume re-import {file_date} from {rel_path}"
        notes = (existing.get("notes") or "").strip()
        if reimport_note not in notes:
            patch["notes"] = f"{reimport_note}\n\n{notes}".strip() if notes else reimport_note
        if patch:
            sb.table("candidates").update(patch).eq("id", existing["id"]).execute()
            existing = {**existing, **patch}
            print(f"Updated: {full_name} ({source})", flush=True)
        else:
            print(f"Unchanged: {full_name} ({source})", flush=True)
        _register_candidate_keys(keys, existing)
        append_last_processed(path.name)
        return "updated"

    if profile_path.exists():
        append_last_processed(path.name)
        print(f"Skip insert — profile exists without DB row: {full_name}", flush=True)
        return "skipped"

    write_profile_stub(
        slug=slug,
        full_name=full_name,
        source=source,
        import_date=import_date,
        email=email,
        linkedin_url=linkedin_url,
        current_title=title,
        current_company=company,
    )

    payload = {
        "role_id": role_id,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "linkedin_url": linkedin_url,
        "current_title": title,
        "current_company": company,
        "source": source,
        "pipeline_stage": "identified",
        "notes": f"Resume import {file_date} from {path.relative_to(INBOX)}",
    }
    inserted = sb.table("candidates").insert(payload).execute().data[0]
    _register_candidate_keys(keys, inserted)
    append_last_processed(path.name)
    print(f"Inserted: {full_name} ({source})", flush=True)
    return "inserted"


def _linkedin_from_text(text: str) -> str | None:
    match = re.search(
        r"(https?://(?:www\.)?linkedin\.com/in/[^\s\"'<>]+|linkedin\.com/in/[^\s\"'<>]+|(?:www\.)?linkedin\.com/in/[^\s\"'<>]+|/in/[a-z0-9\-]+/?)",
        text,
        re.I,
    )
    if not match:
        return None
    url = match.group(1)
    if url.startswith("/in/"):
        url = "https://www.linkedin.com" + url
    elif not url.startswith("http"):
        url = "https://www." + url.lstrip("www.")
    return url.rstrip("/") + "/"


def folder_source(path: Path) -> str:
    for parent in path.parents:
        if parent == INBOX:
            break
        key = parent.name.lower()
        if key in FOLDER_SOURCE:
            return FOLDER_SOURCE[key]
    return "Other"


def find_inbox_resumes() -> list[Path]:
    files: list[Path] = []
    for ext in ("*.pdf", "*.docx"):
        files.extend(INBOX.rglob(ext))
    return sorted(
        p for p in files
        if p.name not in (".gitkeep",) and not p.name.startswith(".")
    )


def rename_to_convention(path: Path, import_date: str | None = None) -> Path | None:
    """Rename inbox file to YYYY-MM-DD-sales-rep-<slug>.pdf; return new path."""
    if RESUME_RE.match(path.name):
        return path

    text = _extract_text(path)
    full_name = _name_from_indeed_filename(INDEED_RESUME_RE.match(path.name).group(1)) if INDEED_RESUME_RE.match(path.name) else None
    if not full_name:
        full_name = _name_from_text(text)
    if not full_name:
        linkedin_url = _linkedin_from_text(text)
        if linkedin_url:
            full_name = _name_from_linkedin_url(linkedin_url)
    if not full_name:
        email = _email_from_text(text)
        if email:
            full_name = _name_from_email(email)
    if not full_name:
        print(f"Skip rename (no name): {path.name}", file=sys.stderr)
        return None

    slug = full_name_to_resume_slug(full_name)
    file_date = import_date or date.fromtimestamp(path.stat().st_mtime).isoformat()
    new_name = f"{file_date}-{RESUME_ROLE_PREFIX}-{slug}.pdf"
    dest = path.parent / new_name

    if path.suffix.lower() == ".docx":
        print(f"Skip rename (docx — convert to PDF first): {path.name}", file=sys.stderr)
        return None

    if dest.exists() and dest.resolve() != path.resolve():
        print(f"Skip rename (target exists): {path.name} -> {new_name}")
        return dest

    if path.name != new_name:
        path.rename(dest)
        print(f"Renamed: {path.name} -> {new_name}")
    return dest


def load_existing_keys(sb, role_id: str) -> dict:
    rows = (
        sb.table("candidates")
        .select("id, full_name, email, linkedin_url, phone, market, pipeline_stage, notes")
        .eq("role_id", role_id)
        .execute()
        .data
    )
    emails: set[str] = set()
    linkedins: set[str] = set()
    slugs: set[str] = set()
    by_slug: dict[str, dict] = {}
    by_email: dict[str, dict] = {}
    by_linkedin: dict[str, dict] = {}
    for row in rows:
        if row.get("email"):
            email_key = row["email"].lower()
            emails.add(email_key)
            by_email[email_key] = row
        if row.get("linkedin_url"):
            linkedin_key = row["linkedin_url"].rstrip("/").lower()
            linkedins.add(linkedin_key)
            by_linkedin[linkedin_key] = row
        slug = full_name_to_resume_slug(row["full_name"])
        slugs.add(slug)
        by_slug[slug] = row
    return {
        "emails": emails,
        "linkedins": linkedins,
        "slugs": slugs,
        "by_slug": by_slug,
        "by_email": by_email,
        "by_linkedin": by_linkedin,
    }


def resolve_existing_candidate(
    keys: dict,
    *,
    slug: str,
    email: str | None,
    linkedin_url: str | None,
) -> dict | None:
    """Match existing row by resume slug, email, or LinkedIn (no duplicate inserts)."""
    if slug in keys["by_slug"]:
        return keys["by_slug"][slug]
    if email:
        match = keys["by_email"].get(email.lower())
        if match:
            return match
    if linkedin_url:
        match = keys["by_linkedin"].get(linkedin_url.rstrip("/").lower())
        if match:
            return match
    return None


def _register_candidate_keys(keys: dict, row: dict) -> None:
    slug = full_name_to_resume_slug(row["full_name"])
    keys["slugs"].add(slug)
    keys["by_slug"][slug] = row
    if row.get("email"):
        email_key = row["email"].lower()
        keys["emails"].add(email_key)
        keys["by_email"][email_key] = row
    if row.get("linkedin_url"):
        linkedin_key = row["linkedin_url"].rstrip("/").lower()
        keys["linkedins"].add(linkedin_key)
        keys["by_linkedin"][linkedin_key] = row


def append_last_processed(filename: str) -> None:
    existing = LAST_PROCESSED.read_text().splitlines() if LAST_PROCESSED.exists() else []
    if filename not in existing:
        with LAST_PROCESSED.open("a") as handle:
            if existing and existing[-1]:
                handle.write("\n")
            handle.write(filename)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process imports/inbox resumes")
    parser.add_argument("--rename-only", action="store_true")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    files = find_inbox_resumes()
    if not files:
        print(f"No resume files in {INBOX}")
        return 0

    print(f"Found {len(files)} file(s) in inbox (including subfolders)")
    for path in files:
        rel = path.relative_to(INBOX)
        print(f"  {rel} [{folder_source(path)}]")

    renamed = 0
    for path in files:
        if RESUME_RE.match(path.name):
            continue
        result = rename_to_convention(path, args.date)
        if result and result.name != path.name:
            renamed += 1

    print(f"Renamed {renamed} file(s)")
    if args.rename_only:
        return 0

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = (
        sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    )
    keys = load_existing_keys(sb, role_id)

    inserted = updated = skipped = errors = 0
    for path in find_inbox_resumes():
        if not RESUME_RE.match(path.name):
            continue
        outcome = sync_resume_pdf(
            path, sb, role_id, keys, import_date=args.date
        )
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        elif outcome == "skipped":
            skipped += 1
        else:
            errors += 1

    print(
        f"Sync complete — {inserted} inserted, {updated} updated, "
        f"{skipped} skipped, {errors} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
