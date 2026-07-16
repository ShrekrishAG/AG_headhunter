"""Role definitions for Slack ZipRecruiter sourcing (prescreen + export behavior)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RoleDefinition:
    slug: str
    title: str
    qualified_min_score: int
    sync_dashboard: bool
    rubric_categories: tuple[dict[str, int | str], ...]
    score_bands: tuple[tuple[int, str], ...]
    red_flag_max_deduction: int = 15


SALES_REP = RoleDefinition(
    slug="sales-representative",
    title="Project Sales Representative",
    qualified_min_score=65,
    sync_dashboard=True,
    rubric_categories=(
        {"label": "Sales Experience", "max_points": 25},
        {"label": "Project / Field Experience", "max_points": 20},
        {"label": "Customer Relationship Skills", "max_points": 15},
        {"label": "Communication & Professionalism", "max_points": 15},
        {"label": "Technical / Tool Fit", "max_points": 10},
        {"label": "Work Ethic & Culture Fit Signals", "max_points": 10},
    ),
    score_bands=(
        (85, "Strong interview"),
        (70, "Good candidate"),
        (60, "Phone screen"),
        (0, "Likely not a fit"),
    ),
)

VP_OF_GROWTH = RoleDefinition(
    slug="vp-of-growth",
    title="VP of Growth & Revenue Systems",
    qualified_min_score=70,
    sync_dashboard=False,
    rubric_categories=(
        {"label": "Revenue / Growth Leadership", "max_points": 25},
        {"label": "Full-Funnel Systems", "max_points": 20},
        {"label": "Marketing + Sales Integration", "max_points": 15},
        {"label": "Data, Dashboards & Forecasting", "max_points": 15},
        {"label": "Training, Coaching & Execution", "max_points": 15},
        {"label": "Industry & Builder Fit", "max_points": 10},
    ),
    score_bands=(
        (85, "Strong interview"),
        (70, "Good candidate"),
        (60, "Phone screen"),
        (0, "Likely not a fit"),
    ),
)

ROLES: dict[str, RoleDefinition] = {
    SALES_REP.slug: SALES_REP,
    VP_OF_GROWTH.slug: VP_OF_GROWTH,
}

ROLE_ALIASES: dict[str, str] = {
    "sales-rep": SALES_REP.slug,
    "sales": SALES_REP.slug,
    "psr": SALES_REP.slug,
    "vp": VP_OF_GROWTH.slug,
    "vp-growth": VP_OF_GROWTH.slug,
    "vp-of-growth": VP_OF_GROWTH.slug,
    "growth": VP_OF_GROWTH.slug,
}

# ZipRecruiter project name hints → role (substring match, case-insensitive)
PROJECT_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("dfo - vp headhunter", VP_OF_GROWTH.slug),
    ("vp headhunter", VP_OF_GROWTH.slug),
)


def role_slug_for_project_name(project_name: str) -> str | None:
    name = (project_name or "").strip().lower()
    if not name:
        return None
    for hint, slug in PROJECT_ROLE_HINTS:
        hint_lower = hint.lower()
        if hint_lower in name or name in hint_lower:
            return slug
    return None


def normalize_role_slug(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return default_role_slug()
    if raw in ROLES:
        return raw
    return ROLE_ALIASES.get(raw, raw)


def resolve_role_slug(
    *,
    explicit_role: str | None = None,
    project_query: str = "",
) -> str:
    if explicit_role:
        return normalize_role_slug(explicit_role)
    hinted = role_slug_for_project_name(project_query)
    if hinted:
        return hinted
    return default_role_slug()


def default_role_slug() -> str:
    return normalize_role_slug(os.getenv("DEFAULT_ROLE_SLUG", SALES_REP.slug))


def get_role(role_slug: str | None = None) -> RoleDefinition:
    slug = normalize_role_slug(role_slug)
    role = ROLES.get(slug)
    if role is None:
        known = ", ".join(sorted(ROLES))
        raise ValueError(f"Unknown role `{slug}`. Known roles: {known}")
    return role


def parse_role_from_text(text: str) -> str | None:
    if not text.strip():
        return None
    tokens = (
        r"sales-representative|sales-rep|sales|psr|"
        r"vp-of-growth|vp-growth|vp|growth"
    )
    match = re.search(rf"\b(?:for|role)\s+({tokens})\b", text, flags=re.I)
    if not match:
        return None
    return normalize_role_slug(match.group(1))


def strip_role_tokens(text: str) -> str:
    cleaned = text
    cleaned = re.sub(
        r"\bfor\s+(?:sales-representative|sales-rep|sales|psr|vp-of-growth|vp-growth|vp|growth)\b",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(
        r"\brole\s+(?:sales-representative|sales-rep|sales|psr|vp-of-growth|vp-growth|vp|growth)\b",
        "",
        cleaned,
        flags=re.I,
    )
    return cleaned.strip()


def slack_role_options() -> list[dict[str, str]]:
    return [
        {"text": {"type": "plain_text", "text": role.title}, "value": role.slug}
        for role in ROLES.values()
    ]
