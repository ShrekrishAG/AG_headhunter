"""Phone extraction and normalization for candidate records."""

from __future__ import annotations

import re

PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s.-]?)?"
    r"(?:\(\s*\d{3}\s*\)|\d{3})"
    r"[\s.-]?"
    r"\d{3}"
    r"[\s.-]?"
    r"\d{4}"
    r"(?!\d)"
)


def extract_phone_from_text(text: str) -> str | None:
    for match in PHONE_RE.finditer(text):
        normalized = normalize_phone_us(match.group(0))
        if normalized:
            return normalized
    return None


def normalize_phone_us(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"
