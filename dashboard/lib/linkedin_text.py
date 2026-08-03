"""Fetch best-effort public LinkedIn profile text for resume scoring."""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

LINKEDIN_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = TAG_RE.sub(" ", unescape(html))
    return WS_RE.sub(" ", text).strip()


def fetch_linkedin_profile_text(linkedin_url: str, *, timeout: int = 20) -> str | None:
    """Best-effort public profile text. Often blocked by LinkedIn login wall."""
    url = (linkedin_url or "").strip()
    if not url or "linkedin.com" not in url.lower():
        return None

    req = Request(
        url,
        headers={
            "User-Agent": LINKEDIN_UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        html = urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        logger.info("LinkedIn fetch failed for %s: %s", url, exc)
        return None

    chunks: list[str] = []
    for pattern in (
        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
        r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
        r"<title>([^<]+)</title>",
    ):
        match = re.search(pattern, html, re.I)
        if match:
            chunks.append(unescape(match.group(1)).strip())

    # Public profile sometimes embeds JSON-LD Person data.
    for match in re.finditer(
        r'"@type"\s*:\s*"Person"[^}]{0,4000}',
        html,
        re.I,
    ):
        chunk = _strip_html(match.group(0))
        if len(chunk) > 40:
            chunks.append(chunk)

    body = _strip_html(html)
    # Drop obvious login-wall boilerplate.
    lower = body.lower()
    if "sign in" in lower and "join now" in lower and len(body) < 2500:
        useful = " | ".join(c for c in chunks if c)
        return useful if len(useful) >= 80 else None

    if len(body) > 400:
        chunks.append(body[:8000])

    text = "\n\n".join(dict.fromkeys(c for c in chunks if c))
    if len(text) < 80:
        return None
    return text[:12000]
