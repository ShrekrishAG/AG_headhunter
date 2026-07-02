"""Project Sales Rep resume rubric — 100-point scoring."""

from __future__ import annotations

from lib.constants import QUALIFIED_MIN_SCORE, RUBRIC_CATEGORIES, SCORE_BANDS


def clamp_score(value: int, max_points: int) -> int:
    return max(0, min(max_points, int(value)))


def compute_total(category_scores: dict[str, int], red_flag_deduction: int = 0) -> int:
    subtotal = 0
    for cat in RUBRIC_CATEGORIES:
        subtotal += clamp_score(category_scores.get(cat["label"], 0), cat["max_points"])
    deduction = max(0, min(15, int(red_flag_deduction)))
    return max(0, min(100, subtotal - deduction))


def recommendation_for_total(total: int) -> str:
    for min_score, label in SCORE_BANDS:
        if total >= min_score:
            return label
    return SCORE_BANDS[-1][1]


def qualifies_for_pipeline(total: int, recommendation: str | None = None) -> bool:
    rec = recommendation or recommendation_for_total(total)
    return total >= QUALIFIED_MIN_SCORE and rec in ("Strong interview", "Good candidate")


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
