"""Score locked pipeline profile text against a role resume rubric."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from zr.headhunter_pipeline import accord_dashboard_dir
from zr.locked_pipeline import LockedCandidate
from zr.role_config import RoleDefinition, get_role

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    dashboard = accord_dashboard_dir()
    if dashboard:
        return dashboard.parent
    return Path(__file__).resolve().parents[2]


def _load_role_text(role: RoleDefinition, filename: str) -> str:
    path = _repo_root() / "roles" / role.slug / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _load_openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    dashboard = accord_dashboard_dir()
    if dashboard:
        env_path = dashboard / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            key = os.getenv("OPENAI_API_KEY", "").strip()
    return key


def _clamp_score(value: int, max_points: int) -> int:
    return max(0, min(max_points, int(value)))


def compute_total(
    role: RoleDefinition,
    category_scores: dict[str, int],
    red_flag_deduction: int = 0,
) -> int:
    subtotal = 0
    for cat in role.rubric_categories:
        label = str(cat["label"])
        max_points = int(cat["max_points"])
        subtotal += _clamp_score(category_scores.get(label, 0), max_points)
    deduction = max(0, min(role.red_flag_max_deduction, int(red_flag_deduction)))
    return max(0, min(100, subtotal - deduction))


def recommendation_for_total(role: RoleDefinition, total: int) -> str:
    for min_score, label in role.score_bands:
        if total >= min_score:
            return label
    return role.score_bands[-1][1]


def qualifies_for_pipeline(role: RoleDefinition, total: int) -> bool:
    return total >= role.qualified_min_score


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


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


def score_candidate_profile(
    candidate: LockedCandidate,
    *,
    role_slug: str | None = None,
) -> LockedCandidate:
    role = get_role(role_slug)
    api_key = _load_openai_key()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set — add it to slack-zr-agent/.env or dashboard/.env"
        )

    from openai import OpenAI

    scorecard = _load_role_text(role, "scorecard.md")
    brief = _load_role_text(role, "brief.md")
    sample = _load_role_text(role, "sample-walkthrough.md")
    category_labels = [str(cat["label"]) for cat in role.rubric_categories]

    prompt = f"""You are the Accord Group recruiting agent. Score this candidate for **{role.title}** using the 100-point resume rubric.

You only have ZipRecruiter profile text (headline + work experience). Contact info may be hidden — score from visible career evidence only.

## Role brief
{brief[:4000]}

## Scorecard rubric
{scorecard[:8000]}

## Sample scored candidate (format reference)
{sample[:2500]}

## Candidate
Name: {candidate.name}
Headline: {candidate.headline or "—"}

## Profile text
{candidate.profile_text[:10000]}

Return ONLY valid JSON (no markdown fences):
{{
  "summary": "2-3 sentences on fit for {role.title}",
  "categories": {{
    "{category_labels[0]}": {{"score": 0-{role.rubric_categories[0]["max_points"]}, "evidence": "short"}},
    ... one key per category label exactly ...
  }},
  "red_flag_deduction": 0-{role.red_flag_max_deduction},
  "red_flag_notes": "brief or none"
}}
"""

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_PRESCREEN_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    payload = _parse_llm_json(response.choices[0].message.content or "{}")

    category_scores: dict[str, int] = {}
    categories = payload.get("categories") or {}
    if isinstance(categories, dict):
        for label in category_labels:
            entry = categories.get(label) or {}
            if isinstance(entry, dict):
                category_scores[label] = int(entry.get("score") or 0)
            else:
                category_scores[label] = int(entry or 0)

    total = compute_total(
        role, category_scores, int(payload.get("red_flag_deduction") or 0)
    )
    recommendation = recommendation_for_total(role, total)

    candidate.total_score = total
    candidate.recommendation = recommendation
    candidate.summary = str(payload.get("summary") or "").strip() or None
    candidate.qualifies = qualifies_for_pipeline(role, total)
    candidate.metadata["role_slug"] = role.slug
    candidate.metadata["category_scores"] = category_scores
    candidate.metadata["red_flag_notes"] = payload.get("red_flag_notes")
    return candidate


def score_candidates(
    candidates: list[LockedCandidate],
    *,
    role_slug: str | None = None,
) -> list[LockedCandidate]:
    scored: list[LockedCandidate] = []
    for candidate in candidates:
        try:
            scored.append(score_candidate_profile(candidate, role_slug=role_slug))
        except Exception as error:
            logger.warning("Prescreen failed for %s: %s", candidate.name, error)
            candidate.total_score = 0
            candidate.recommendation = "Likely not a fit"
            candidate.summary = f"Scoring error: {error}"
            candidate.qualifies = False
            scored.append(candidate)
    return scored
