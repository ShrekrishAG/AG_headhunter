#!/usr/bin/env python3
"""Fetch LinkedIn profile photos and cache them in Supabase Storage."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
INBOX = ROOT / "imports" / "inbox"
HEADSHOTS_DIR = INBOX / "LinkedIn" / "Headshots"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
sys.path.insert(0, str(DASHBOARD))

from lib.avatar import initials_avatar_url  # noqa: E402
from lib.resume_slug import full_name_to_resume_slug  # noqa: E402
from lib.linkedin_photo import extension_for_content_type, fetch_linkedin_photo  # noqa: E402
from lib.resume_photo import extract_resume_photo  # noqa: E402

load_dotenv(DASHBOARD / ".env")

BUCKET = "avatars"
ROLE_SLUG = "sales-representative"


def _public_url(sb, storage_path: str) -> str:
    return sb.storage.from_(BUCKET).get_public_url(storage_path)


def _upload_bytes(
    sb,
    storage_path: str,
    data: bytes,
    content_type: str,
) -> str:
    sb.storage.from_(BUCKET).upload(
        storage_path,
        data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return _public_url(sb, storage_path)


def _upload_initials(sb, slug: str, full_name: str) -> str:
    url = initials_avatar_url(full_name, size=256)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as response:
        data = response.read()
    storage_path = f"{ROLE_SLUG}/{slug}.png"
    return _upload_bytes(sb, storage_path, data, "image/png")


def _content_type_for_path(path: Path) -> str:
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return mapping.get(path.suffix.lower(), "image/jpeg")


def _local_headshot(slug: str, full_name: str) -> tuple[bytes, str] | None:
    """Use manually dropped headshots from imports/inbox/LinkedIn/Headshots/."""
    if not HEADSHOTS_DIR.is_dir():
        return None

    candidates: list[Path] = []
    for path in sorted(HEADSHOTS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        file_slug = full_name_to_resume_slug(path.stem.strip())
        if file_slug == slug:
            candidates.append(path)

    if not candidates:
        return None

    path = candidates[-1]
    return path.read_bytes(), _content_type_for_path(path)


def _local_resume_pdf(slug: str) -> Path | None:
    from lib.constants import RESUME_ROLE_PREFIX

    matches = sorted(INBOX.rglob(f"*-{RESUME_ROLE_PREFIX}-{slug}.pdf"))
    return matches[-1] if matches else None


def _download_resume_pdf(resume_url: str) -> bytes | None:
    try:
        req = Request(resume_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type and not resume_url.lower().endswith(".pdf"):
                return None
            return response.read()
    except (HTTPError, URLError, TimeoutError):
        return None


def _resume_photo(slug: str, resume_url: str | None) -> tuple[bytes, str] | None:
    local_pdf = _local_resume_pdf(slug)
    if local_pdf:
        return extract_resume_photo(local_pdf)
    if resume_url:
        pdf_bytes = _download_resume_pdf(resume_url)
        if pdf_bytes:
            return extract_resume_photo(pdf_bytes)
    return None


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    role_id = (
        sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    )
    candidates = (
        sb.table("candidates")
        .select("id, full_name, linkedin_url, resume_url, avatar_url")
        .eq("role_id", role_id)
        .execute()
        .data
    )

    synced = 0
    for candidate in candidates:
        slug = full_name_to_resume_slug(candidate["full_name"])
        storage_base = f"{ROLE_SLUG}/{slug}"
        avatar_url = None
        source = "initials"

        photo = _local_headshot(slug, candidate["full_name"])
        if photo:
            data, content_type = photo
            ext = extension_for_content_type(content_type)
            storage_path = f"{storage_base}.{ext}"
            avatar_url = _upload_bytes(sb, storage_path, data, content_type)
            source = "local-headshot"

        if not avatar_url and candidate.get("linkedin_url"):
            photo = fetch_linkedin_photo(
                candidate["linkedin_url"],
                profile_name=candidate["full_name"],
            )
            if photo:
                data, content_type = photo
                ext = extension_for_content_type(content_type)
                storage_path = f"{storage_base}.{ext}"
                avatar_url = _upload_bytes(sb, storage_path, data, content_type)
                source = "linkedin"

        if not avatar_url:
            photo = _resume_photo(slug, candidate.get("resume_url"))
            if photo:
                data, content_type = photo
                ext = extension_for_content_type(content_type)
                storage_path = f"{storage_base}.{ext}"
                avatar_url = _upload_bytes(sb, storage_path, data, content_type)
                source = "resume"

        if not avatar_url:
            avatar_url = _upload_initials(sb, slug, candidate["full_name"])

        sb.table("candidates").update({"avatar_url": avatar_url}).eq(
            "id", candidate["id"]
        ).execute()
        print(f"{source}: {candidate['full_name']}")
        synced += 1

    print(f"Done — {synced} avatar(s) synced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
