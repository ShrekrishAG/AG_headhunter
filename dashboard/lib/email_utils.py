"""Email extraction and normalization for candidate records."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

SKIP_EMAIL_DOMAINS = (
    "linkedin.com",
    "example.com",
    "email.com",
    "sentry.io",
    "wixpress.com",
)


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().lower().rstrip(".,;)")
    match = EMAIL_RE.search(value)
    if not match:
        return None
    email = match.group(0)
    domain = email.rsplit("@", 1)[-1]
    if any(domain == skip or domain.endswith("." + skip) for skip in SKIP_EMAIL_DOMAINS):
        return None
    return email


def extract_email_from_text(text: str) -> str | None:
    for match in EMAIL_RE.finditer(text):
        email = normalize_email(match.group(0))
        if email:
            return email
    return None
