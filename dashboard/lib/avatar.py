"""Avatar URL helpers (no Streamlit dependency)."""

from __future__ import annotations

from urllib.parse import quote


def initials_avatar_url(full_name: str, size: int = 128) -> str:
    return (
        "https://ui-avatars.com/api/"
        f"?name={quote(full_name)}&size={size}&background=E8EEF2&color=334155&bold=true"
    )
