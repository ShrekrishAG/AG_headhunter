"""Fetch and cache LinkedIn profile photos."""

from __future__ import annotations

import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

LINKEDIN_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
PROFILE_PHOTO_URL = re.compile(
    r"https://media\.licdn\.com/dms/image/[^\"'\s<>]+profile-displayphoto[^\"'\s<>]+",
    re.I,
)
EXCLUDED_URL_MARKERS = re.compile(
    r"company-logo|profile-displayphoto-background|brand-logo|school-logo",
    re.I,
)
GHOST_URL = re.compile(r"static\.licdn\.com", re.I)
IMG_TAG = re.compile(r"<img[^>]+>", re.I | re.S)


def _normalize_url(url: str) -> str:
    return url.replace("&amp;", "&").strip()


def _is_profile_display_photo(url: str) -> bool:
    if not url or GHOST_URL.search(url):
        return False
    if EXCLUDED_URL_MARKERS.search(url):
        return False
    return bool(PROFILE_PHOTO_URL.fullmatch(url))


def _name_matches_alt(full_name: str, alt: str) -> bool:
    parts = [p for p in re.sub(r"[.]", " ", full_name).split() if len(p) > 1]
    if not parts:
        return False
    alt_lower = alt.lower()
    return all(part.lower() in alt_lower for part in parts)


def _photo_url_from_img_tag(tag: str) -> str | None:
    for attr in ("data-delayed-url", "src", "content"):
        match = re.search(rf'{attr}="([^"]+)"', tag, re.I)
        if match:
            url = _normalize_url(match.group(1))
            if _is_profile_display_photo(url):
                return url
    return None


def extract_profile_photo_url(page_html: str, profile_name: str | None = None) -> str | None:
    """Return the profile owner's display photo URL, not feed/recommendation avatars."""
    for tag_match in IMG_TAG.finditer(page_html):
        tag = tag_match.group(0)
        if "top-card__profile-image" not in tag:
            continue
        photo_url = _photo_url_from_img_tag(tag)
        if photo_url:
            return photo_url

    if profile_name:
        for tag_match in IMG_TAG.finditer(page_html):
            tag = tag_match.group(0)
            alt_match = re.search(r'alt="([^"]*)"', tag, re.I)
            if not alt_match or not _name_matches_alt(profile_name, alt_match.group(1)):
                continue
            photo_url = _photo_url_from_img_tag(tag)
            if photo_url:
                return photo_url

    person_match = re.search(
        r'"@type"\s*:\s*"Person"[^}]*?"image"\s*:\s*\{[^}]*?"contentUrl"\s*:\s*"([^"]+)"',
        page_html,
        re.I | re.S,
    )
    if person_match:
        photo_url = _normalize_url(person_match.group(1))
        if _is_profile_display_photo(photo_url):
            return photo_url

    return None


def profile_name_from_page(page_html: str) -> str | None:
    title_match = re.search(r"<title>([^<|]+)", page_html, re.I)
    if title_match:
        return title_match.group(1).strip()
    return None


def fetch_linkedin_photo(
    linkedin_url: str,
    profile_name: str | None = None,
) -> tuple[bytes, str] | None:
    """Return (image_bytes, content_type) or None if unavailable."""
    page_req = Request(
        linkedin_url,
        headers={
            "User-Agent": LINKEDIN_UA,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        page_html = urlopen(page_req, timeout=20).read().decode("utf-8", "ignore")
    except (HTTPError, URLError, TimeoutError):
        return None

    resolved_name = profile_name or profile_name_from_page(page_html)
    photo_url = extract_profile_photo_url(page_html, resolved_name)
    if not photo_url:
        return None

    photo_req = Request(
        photo_url,
        headers={
            "User-Agent": LINKEDIN_UA,
            "Referer": "https://www.linkedin.com/",
        },
    )
    try:
        with urlopen(photo_req, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "image/jpeg")
            if not content_type.startswith("image/"):
                return None
            return response.read(), content_type.split(";")[0]
    except (HTTPError, URLError, TimeoutError):
        return None


def extension_for_content_type(content_type: str) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    return mapping.get(content_type, "jpg")


def linkedin_slug(linkedin_url: str | None) -> str | None:
    if not linkedin_url:
        return None
    path = urlparse(linkedin_url).path.rstrip("/")
    if "/in/" not in path:
        return None
    return path.rsplit("/in/", 1)[-1]
