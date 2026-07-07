"""Friendly market labels for outreach templates."""

from __future__ import annotations

# ZipRecruiter project_name values → copy used in SMS/email
OUTREACH_MARKET_LABELS: dict[str, str] = {
    "TGC - KC, MO": "Kansas City",
    "TGC - Springfield MO": "Springfield",
    "TGC - St Louis": "St. Louis",
    "TGC - Wichita, KS": "Wichita",
    "TGC - madison WI": "Madison",
}


def outreach_market_label(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return "your area"
    key = str(raw).strip()
    if key in OUTREACH_MARKET_LABELS:
        return OUTREACH_MARKET_LABELS[key]
    if key.startswith("TGC - "):
        return key[6:].strip()
    return key
