"""Parse agent pre-screen data from Supabase notes and candidate profile files."""

from __future__ import annotations

import re
from pathlib import Path

from lib.resume_slug import full_name_to_resume_slug
from lib.rubric import recommendation_emoji

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROLE_SLUG = "sales-representative"

TOTAL_SCORE_PATTERN = re.compile(
    r"\*\*Total score:\*\*\s*(\d+)\s*/\s*100",
    re.I,
)
LEGACY_WEIGHTED_PATTERN = re.compile(r"\*\*Weighted total:\*\*\s*([\d.]+)")
NOTES_SCORE_PATTERN = re.compile(r"·\s*(\d+)\s*/\s*100\s*·")
LEGACY_NOTES_SCORE_PATTERN = re.compile(r"·\s*(\d+\.\d{2})\s*·")

RECOMMENDATION_PATTERN = re.compile(
    r"\*\*Recommendation:\*\*\s*"
    r"(Strong interview|Good candidate|Phone screen|Likely not a fit)",
    re.I,
)
LEGACY_RECOMMEND_PATTERN = re.compile(
    r"\*\*Recommendation:\*\*\s*(Recommend|Consider|Pass)",
    re.I,
)
NOTES_RECOMMEND_PATTERN = re.compile(
    r"·\s*(Strong interview|Good candidate|Phone screen|Likely not a fit)\s*(?:·|$)",
    re.I,
)

RED_FLAGS_PATTERN = re.compile(r"\*\*Red flags / deductions:\*\*\s*(-?\d+)", re.I)
SCORECARD_ROW_PATTERN = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|",
    re.M,
)
RISKS_PATTERN = re.compile(r"## Risks\s*\n\n((?:- .+\n?)+)", re.M)


def profile_path_for(candidate: dict, role_slug: str = DEFAULT_ROLE_SLUG) -> Path:
    slug = full_name_to_resume_slug(candidate["full_name"])
    return REPO_ROOT / "candidates" / role_slug / slug / "profile.md"


def _read_profile_text(candidate: dict, role_slug: str = DEFAULT_ROLE_SLUG) -> str | None:
    profile = profile_path_for(candidate, role_slug)
    if not profile.exists():
        return None
    return profile.read_text(encoding="utf-8")


def parse_agent_score(candidate: dict) -> int | None:
    text = _read_profile_text(candidate)
    if text:
        match = TOTAL_SCORE_PATTERN.search(text)
        if match:
            return int(match.group(1))
        legacy = LEGACY_WEIGHTED_PATTERN.search(text)
        if legacy:
            return int(round(float(legacy.group(1)) * 25))

    notes = candidate.get("notes") or ""
    match = NOTES_SCORE_PATTERN.search(notes)
    if match:
        return int(match.group(1))
    legacy = LEGACY_NOTES_SCORE_PATTERN.search(notes)
    if legacy:
        return int(round(float(legacy.group(1)) * 25))
    return None


def parse_agent_recommendation(candidate: dict) -> str | None:
    text = _read_profile_text(candidate)
    if text:
        match = RECOMMENDATION_PATTERN.search(text)
        if match:
            return _normalize_recommendation(match.group(1))
        legacy = LEGACY_RECOMMEND_PATTERN.search(text)
        if legacy:
            return _legacy_to_new_recommendation(legacy.group(1), parse_agent_score(candidate))

    notes = candidate.get("notes") or ""
    match = NOTES_RECOMMEND_PATTERN.search(notes)
    if match:
        return _normalize_recommendation(match.group(1))
    return None


def _normalize_recommendation(value: str) -> str:
    v = value.strip().lower()
    if "strong" in v:
        return "Strong interview"
    if "good" in v:
        return "Good candidate"
    if "phone" in v:
        return "Phone screen"
    return "Likely not a fit"


def _legacy_to_new_recommendation(legacy: str, score: int | None) -> str:
    if score is not None:
        from lib.rubric import recommendation_for_total

        return recommendation_for_total(score)
    mapping = {
        "Recommend": "Strong interview",
        "Consider": "Good candidate",
        "Pass": "Likely not a fit",
    }
    return mapping.get(legacy.capitalize(), "Likely not a fit")


def _parse_scorecard_rows(text: str) -> list[tuple[str, int, int, str]]:
    rows: list[tuple[str, int, int, str]] = []
    for match in SCORECARD_ROW_PATTERN.finditer(text):
        label, max_pts, score, evidence = (
            match.group(1).strip(),
            int(match.group(2)),
            int(match.group(3)),
            match.group(4).strip(),
        )
        if label.lower() in ("category", "max", "score", "evidence", "total"):
            continue
        if "red flag" in label.lower():
            continue
        rows.append((label, max_pts, score, evidence))
    return rows


def _parse_risk_bullets(text: str) -> list[str]:
    block = RISKS_PATTERN.search(text)
    if not block:
        return []
    return [
        line.lstrip("- ").strip()
        for line in block.group(1).splitlines()
        if line.strip().startswith("-")
    ]


def load_agent_score_rationale(candidate: dict, role_slug: str = DEFAULT_ROLE_SLUG) -> str | None:
    text = _read_profile_text(candidate, role_slug)
    if not text:
        return None

    parts: list[str] = []
    scorecard = _parse_scorecard_rows(text)
    if scorecard:
        parts.append("**Score breakdown:**")
        for label, max_pts, score, evidence in scorecard:
            parts.append(f"- **{label} ({score}/{max_pts}):** {evidence}")

    red_flags = RED_FLAGS_PATTERN.search(text)
    if red_flags:
        parts.append(f"**Red flags / deductions:** {red_flags.group(1)} points")

    risks = _parse_risk_bullets(text)
    if risks:
        parts.append("**Risks / gaps:**")
        for risk in risks:
            parts.append(f"- {risk}")

    return "\n\n".join(parts) if parts else None


def sort_by_agent_score(candidates: list[dict]) -> list[dict]:
    return sorted(
        candidates,
        key=lambda c: (
            -(parse_agent_score(c) or 0),
            c.get("full_name") or "",
        ),
    )


def rank_in_group(sorted_candidates: list[dict]) -> dict[str, int]:
    return {c["id"]: index for index, c in enumerate(sorted_candidates, start=1)}


def format_recommendation_label(recommendation: str | None) -> str:
    if not recommendation:
        return "Recommendation: —"
    return f"Recommendation: {recommendation}"


def format_agent_rank(rank: int, candidate: dict) -> str:
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    parts = [f"#{rank}"]
    if score is not None:
        parts.append(f"{score}/100")
    if rec:
        parts.append(format_recommendation_label(rec))
    return " · ".join(parts)


def format_score_badge(candidate: dict) -> str:
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    if score is None:
        return "⏳ **Not scored yet**"
    emoji = recommendation_emoji(rec)
    return f"{emoji} **{score}/100** · {format_recommendation_label(rec)}"
