"""Resume rubric helpers — 100-point scoring (role-aware)."""

from __future__ import annotations

from lib.constants import (
    QUALIFIED_MIN_SCORE,
    ROLE_SLUG,
    RUBRIC_CATEGORIES,
    SCORE_BANDS,
    qualified_min_score_for_slug,
    rubric_categories_for_slug,
)


def clamp_score(value: int, max_points: int) -> int:
    return max(0, min(max_points, int(value)))


def compute_total(
    category_scores: dict[str, int],
    red_flag_deduction: int = 0,
    *,
    role_slug: str | None = None,
) -> int:
    categories = (
        rubric_categories_for_slug(role_slug)
        if role_slug
        else RUBRIC_CATEGORIES
    )
    subtotal = 0
    for cat in categories:
        subtotal += clamp_score(category_scores.get(cat["label"], 0), cat["max_points"])
    deduction = max(0, min(15, int(red_flag_deduction)))
    return max(0, min(100, subtotal - deduction))


def recommendation_for_total(total: int) -> str:
    for min_score, label in SCORE_BANDS:
        if total >= min_score:
            return label
    return SCORE_BANDS[-1][1]


def qualifies_for_pipeline(
    total: int,
    recommendation: str | None = None,
    *,
    role_slug: str | None = None,
) -> bool:
    threshold = (
        qualified_min_score_for_slug(role_slug)
        if role_slug
        else QUALIFIED_MIN_SCORE
    )
    return total >= threshold


def recommendation_emoji(recommendation: str | None) -> str:
    if not recommendation:
        return "⏳"
    key = recommendation.lower()
    if "strong" in key:
        return "🟢"
    if "good" in key:
        return "🔵"
    if "phone" in key:
        return "🟡"
    return "🔴"
