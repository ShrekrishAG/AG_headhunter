"""Agent resume pre-screen: detect unscored candidates and write scored profiles."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from lib.agent_prescreen import parse_agent_score
from lib.constants import DEFAULT_OWNER, RED_FLAG_MAX_DEDUCTION, ROLE_SLUG, RUBRIC_CATEGORIES
from lib.resume_slug import full_name_to_resume_slug
from lib.rubric import compute_total, qualifies_for_pipeline, recommendation_for_total

REPO_ROOT = Path(__file__).resolve().parents[2]
INBOX = REPO_ROOT / "imports" / "inbox"
CANDIDATES_DIR = REPO_ROOT / "candidates" / ROLE_SLUG
SCORECARD_PATH = REPO_ROOT / "roles" / ROLE_SLUG / "scorecard.md"
BRIEF_PATH = REPO_ROOT / "roles" / ROLE_SLUG / "brief.md"
SAMPLE_PATH = REPO_ROOT / "roles" / ROLE_SLUG / "sample-walkthrough.md"

PENDING_MARKERS = (
    "Pending resume pre-screen",
    "Pending agent pre-screen",
)
TOTAL_SCORE_PATTERN = re.compile(r"\*\*Total score:\*\*\s*(\d+)\s*/\s*100", re.I)


def profile_path_for_slug(slug: str) -> Path:
    return CANDIDATES_DIR / slug / "profile.md"


def profile_is_scored(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if any(marker in text for marker in PENDING_MARKERS):
        return False
    return bool(TOTAL_SCORE_PATTERN.search(text))


def resume_pdf_for_slug(slug: str) -> Path | None:
    from lib.constants import RESUME_ROLE_PREFIX

    matches = sorted(INBOX.rglob(f"*-{RESUME_ROLE_PREFIX}-{slug}.pdf"))
    return matches[-1] if matches else None


def pdftotext(path: Path) -> str:
    from lib.pdf_text import extract_pdf_text

    return extract_pdf_text(path)


def list_unscored_from_supabase(rows: list[dict]) -> list[dict]:
    unscored: list[dict] = []
    for row in rows:
        slug = full_name_to_resume_slug(row["full_name"])
        profile = profile_path_for_slug(slug)
        if parse_agent_score(row) is not None and profile_is_scored(profile):
            continue
        if not profile_is_scored(profile):
            unscored.append({**row, "slug": slug, "profile_path": profile})
    return unscored


def _llm_prescreen(
    *,
    resume_text: str,
    profile_text: str,
    scorecard_text: str,
    brief_text: str,
    sample_text: str,
) -> dict[str, Any]:
    from lib.llm_client import chat_completion, llm_configured

    if not llm_configured():
        raise RuntimeError("OPENAI_API_KEY not set — cannot auto prescreen")

    category_labels = [c["label"] for c in RUBRIC_CATEGORIES]
    prompt = f"""You are the Accord Group recruiting agent. Score this Project Sales Representative candidate using the 100-point resume rubric.

Score ONLY from resume evidence. Follow the sample walkthrough style (Jordan Martinez = 77, Good candidate).

## Role brief
{brief_text[:4000]}

## Scorecard rubric
{scorecard_text[:8000]}

## Sample scored candidate (for format reference)
{sample_text[:3000]}

## Existing profile notes (network context — supplemental only)
{profile_text[:2000]}

## Resume text
{resume_text[:12000]}

Return ONLY valid JSON (no markdown fences):
{{
  "current_title": "string or null",
  "current_company": "string or null",
  "summary": "2-4 sentences on fit for Project Sales Rep at Accord Group",
  "categories": {{
    "{category_labels[0]}": {{"score": 0-{RUBRIC_CATEGORIES[0]["max_points"]}, "evidence": "short bullet"}},
    ... one key per category label exactly as above ...
  }},
  "red_flag_deduction": 0-{RED_FLAG_MAX_DEDUCTION},
  "red_flag_notes": "brief explanation of deductions or none",
  "gates": {{
    "valid_license": true/false,
    "us_work_auth": true/false,
    "can_travel": true/false,
    "market_willingness": true/false
  }},
  "gates_summary": "pass/fail summary from resume signals",
  "open_questions": ["...", "..."],
  "risks": ["...", "..."]
}}

Rules:
- Category scores must not exceed each category max.
- red_flag_deduction is subtracted from subtotal (max {RED_FLAG_MAX_DEDUCTION}).
- Do not invent experience not on the resume.
- Use IdealTraits must-haves for gates when inferable.
- Return valid JSON only — no markdown code fences.
"""

    raw = chat_completion(prompt=prompt, max_tokens=2500, json_mode=True)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def render_scored_profile(
    *,
    row: dict,
    slug: str,
    score_data: dict[str, Any],
    existing_text: str,
) -> str:
    category_scores: dict[str, int] = {}
    rows_md: list[str] = []
    for cat in RUBRIC_CATEGORIES:
        label = cat["label"]
        entry = score_data.get("categories", {}).get(label, {})
        score = int(entry.get("score", 0))
        score = max(0, min(cat["max_points"], score))
        evidence = str(entry.get("evidence", "")).strip()
        category_scores[label] = score
        rows_md.append(f"| {label} | {cat['max_points']} | {score} | {evidence} |")

    red_deduction = max(0, min(RED_FLAG_MAX_DEDUCTION, int(score_data.get("red_flag_deduction", 0))))
    total = compute_total(category_scores, red_deduction)
    rec = recommendation_for_total(total)
    stage = "Qualified" if qualifies_for_pipeline(total, rec) else "Identified"

    title = score_data.get("current_title") or row.get("current_title") or "—"
    company = score_data.get("current_company") or row.get("current_company") or "—"
    title_line = " · ".join(x for x in (title, company) if x and x != "—") or "—"

    network_block = ""
    if row.get("personal_network_contact"):
        network_block = f"**Personal network:** {row['personal_network_contact']}  \n"

    context_block = ""
    ctx_match = re.search(
        r"(## Context from network[^\n]*\n(?:.*?\n)*?)(?=\n## |\Z)",
        existing_text,
        re.S,
    )
    if ctx_match:
        context_block = ctx_match.group(1).rstrip() + "\n\n"

    email_line = f"**Email:** {row['email']}  \n" if row.get("email") else ""
    phone_line = f"**Phone:** {row['phone']}  \n" if row.get("phone") else ""

    open_q = score_data.get("open_questions") or ["—"]
    risks = score_data.get("risks") or ["—"]
    next_steps = {
        "Strong interview": "Prioritize for interview — schedule in-person at local office",
        "Good candidate": "Recommend interview if resume aligns with team needs",
        "Phone screen": "5–10 minute phone screen first per IdealTraits process",
        "Likely not a fit": "Hold / pass unless strong referral",
    }
    next_step = next_steps.get(rec, "Review with hiring manager")

    red_notes = score_data.get("red_flag_notes") or "None noted"
    if red_deduction:
        rows_md.append(f"| Red Flags / Deductions | −{RED_FLAG_MAX_DEDUCTION} | −{red_deduction} | {red_notes} |")

    return f"""# Candidate profile

**Role slug:** {ROLE_SLUG}  
**Name:** {row["full_name"]}  
**Current title / company:** {title_line}  
**LinkedIn:** {row.get("linkedin_url") or "—"}  
{email_line}{phone_line}**Source:** {row.get("source") or "—"}  
{network_block}**Stage:** {stage}  
**Market:** {row.get("market") or "—"}  
**Owner:** {DEFAULT_OWNER}  
**Last updated:** {date.today().isoformat()}

## Summary

{score_data.get("summary", "").strip()}

{context_block}## Scorecard

| Category | Max | Score | Evidence |
|----------|-----|-------|----------|
{chr(10).join(rows_md)}

**Red flags / deductions:** −{red_deduction} ({red_notes})  
**Total score:** {total} / 100  
**Must-have gates:** {score_data.get("gates_summary", "see resume")}  
**Recommendation:** {rec}

## Interaction log

| Date | Type | Notes |
|------|------|-------|
| {date.today().isoformat()} | Agent pre-screen | Auto-scored · {total}/100 · {rec} |

## Open questions

{chr(10).join(f"- {q}" for q in open_q)}

## Risks

{chr(10).join(f"- {r}" for r in risks)}

## Next step

- {next_step}
"""


def prescreen_candidate(row: dict, *, slug: str, profile_path: Path) -> bool:
    pdf = resume_pdf_for_slug(slug)
    if not pdf:
        print(f"  Skip prescreen (no PDF): {row['full_name']}", flush=True)
        return False

    resume_text = pdftotext(pdf)
    if not resume_text.strip():
        print(f"  Skip prescreen (empty PDF): {row['full_name']}", flush=True)
        return False

    existing = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    scorecard = SCORECARD_PATH.read_text(encoding="utf-8") if SCORECARD_PATH.exists() else ""
    brief = BRIEF_PATH.read_text(encoding="utf-8") if BRIEF_PATH.exists() else ""
    sample = SAMPLE_PATH.read_text(encoding="utf-8") if SAMPLE_PATH.exists() else ""

    score_data = _llm_prescreen(
        resume_text=resume_text,
        profile_text=existing,
        scorecard_text=scorecard,
        brief_text=brief,
        sample_text=sample,
    )
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        render_scored_profile(row=row, slug=slug, score_data=score_data, existing_text=existing),
        encoding="utf-8",
    )
    print(f"  Prescreened: {row['full_name']}", flush=True)
    return True


def prescreen_all(rows: list[dict]) -> tuple[int, int]:
    unscored = list_unscored_from_supabase(rows)
    if not unscored:
        return 0, 0

    from lib.llm_client import llm_configured

    if not llm_configured():
        print(
            f"⚠ {len(unscored)} candidate(s) need prescreen but OPENAI_API_KEY is not set.",
            flush=True,
        )
        for row in unscored:
            print(f"    - {row['full_name']}", flush=True)
        return 0, len(unscored)

    done = 0
    for i, row in enumerate(unscored):
        if i > 0:
            time.sleep(int(os.getenv("OPENAI_PRESCREEN_DELAY_SECONDS", "2")))
        try:
            if prescreen_candidate(row, slug=row["slug"], profile_path=row["profile_path"]):
                done += 1
        except Exception as exc:
            print(f"  Prescreen failed: {row['full_name']}: {exc}", flush=True)

    still = sum(
        1
        for row in rows
        if not profile_is_scored(profile_path_for_slug(full_name_to_resume_slug(row["full_name"])))
    )
    return done, still
