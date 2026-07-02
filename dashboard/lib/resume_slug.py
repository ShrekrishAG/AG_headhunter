"""Resume filename slug helpers (no Streamlit dependency)."""

from __future__ import annotations

import re
import unicodedata


def full_name_to_resume_slug(full_name: str) -> str:
    """Map 'Luke R. Gunter' -> 'gunter-luke' to match inbox filenames."""
    normalized = unicodedata.normalize("NFKD", full_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    parts = [p for p in re.sub(r"[.]", " ", ascii_name).split() if p]
    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    while len(parts) >= 3 and parts[-1].lower() in suffixes:
        parts = parts[:-1]
    if len(parts) >= 3 and len(parts[1]) == 1:
        first, last = parts[0], parts[-1]
    elif len(parts) >= 2:
        first, last = parts[0], parts[-1]
    else:
        first, last = parts[0], parts[0]
    return f"{last.lower()}-{first.lower()}"
