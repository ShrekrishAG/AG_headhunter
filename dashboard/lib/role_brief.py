"""Role job description (brief.md) load/save per position."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def role_brief_path(role_slug: str) -> Path:
    return REPO_ROOT / "roles" / role_slug / "brief.md"


def role_scorecard_path(role_slug: str) -> Path:
    return REPO_ROOT / "roles" / role_slug / "scorecard.md"


def load_role_brief(role_slug: str) -> str:
    path = role_brief_path(role_slug)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def save_role_brief(role_slug: str, content: str) -> None:
    path = role_brief_path(role_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
