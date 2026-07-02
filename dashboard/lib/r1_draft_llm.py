"""LLM-generated R1 invite drafts (SMS and email)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lib.agent_prescreen import (
    load_agent_score_rationale,
    parse_agent_recommendation,
    parse_agent_score,
    profile_path_for,
)
from lib.constants import ROLE_TITLE
from lib.llm_client import redraft_available, use_template_redraft
from lib.r1_draft_templates import template_redraft_r1_email, template_redraft_r1_sms
from lib.r1_email_invite import build_r1_email_body, build_r1_email_subject
from lib.r1_invite import build_r1_sms_body, first_name

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPANY_CONTEXT_PATH = REPO_ROOT / "company" / "context.md"

SUMMARY_PATTERN = re.compile(r"## Summary\s*\n\n(.*?)(?=\n## |\Z)", re.S)


def _company_context(max_chars: int = 2000) -> str:
    if not COMPANY_CONTEXT_PATH.is_file():
        return ""
    return COMPANY_CONTEXT_PATH.read_text(encoding="utf-8")[:max_chars]


def _profile_summary(candidate: dict) -> str:
    path = profile_path_for(candidate)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    match = SUMMARY_PATTERN.search(text)
    if not match:
        return ""
    return match.group(1).strip()[:800]


def _candidate_context(candidate: dict) -> str:
    parts = [
        f"Name: {candidate.get('full_name') or '—'}",
        f"Role: {ROLE_TITLE}",
        f"Market: {candidate.get('market') or '—'}",
        f"Source: {candidate.get('source') or '—'}",
    ]
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    if score is not None:
        parts.append(f"Resume score: {score}/100")
    if rec:
        parts.append(f"Recommendation: {rec}")
    summary = _profile_summary(candidate)
    if summary:
        parts.append(f"Profile summary: {summary}")
    rationale = load_agent_score_rationale(candidate)
    if rationale:
        parts.append(f"Scoring notes:\n{rationale[:1200]}")
    return "\n".join(parts)


def redraft_r1_sms(
    candidate: dict,
    calendly_url: str,
    *,
    previous_draft: str | None = None,
) -> str:
    if use_template_redraft():
        return template_redraft_r1_sms(
            candidate, calendly_url, previous_draft=previous_draft
        )

    from lib.llm_client import chat_completion, get_draft_model, llm_configured

    if not llm_configured():
        raise RuntimeError("OPENAI_API_KEY not set — cannot redraft messages")

    fn = first_name(candidate.get("full_name") or "")
    fallback = build_r1_sms_body(
        candidate.get("full_name") or "Candidate",
        calendly_url,
    )
    prev_block = ""
    if previous_draft and previous_draft.strip():
        prev_block = f"""
## Previous draft (write a fresh variation — different wording, same intent)
{previous_draft.strip()[:600]}
"""

    prompt = f"""You write recruiting SMS invites for Accord Group (insurance restoration / project sales).

## Company context
{_company_context()}

## Candidate
{_candidate_context(candidate)}

## Requirements
- Plain text only — no markdown, no JSON
- Address candidate as {fn}
- Invite to a ~30-minute phone screen for the {ROLE_TITLE} role
- Include this scheduling link exactly once: {calendly_url.strip()}
- Warm, professional, concise — target under 320 characters if possible, max 480
- Mention Accord Group by name
- Include "Reply STOP to opt out" at the end
- Do not invent compensation or guarantees not in context
{prev_block}
Return ONLY the SMS body text."""

    try:
        raw = chat_completion(prompt=prompt, max_tokens=400, model=get_draft_model()).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:\w+)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw).strip()
        return raw or fallback
    except RuntimeError:
        return template_redraft_r1_sms(
            candidate, calendly_url, previous_draft=previous_draft
        )


def redraft_r1_email(
    candidate: dict,
    calendly_url: str,
    *,
    previous_subject: str | None = None,
    previous_body: str | None = None,
) -> tuple[str, str]:
    if use_template_redraft():
        return template_redraft_r1_email(
            candidate,
            calendly_url,
            previous_subject=previous_subject,
            previous_body=previous_body,
        )

    from lib.llm_client import chat_completion, get_draft_model, llm_configured

    if not llm_configured():
        raise RuntimeError("OPENAI_API_KEY not set — cannot redraft messages")

    fn = first_name(candidate.get("full_name") or "")
    fallback_subject = build_r1_email_subject()
    fallback_body = build_r1_email_body(
        candidate.get("full_name") or "Candidate",
        calendly_url,
    )
    prev_block = ""
    if previous_subject or previous_body:
        prev_block = f"""
## Previous draft (write a fresh variation — different wording, same intent)
Subject: {(previous_subject or '').strip()}
Body:
{(previous_body or '').strip()[:1500]}
"""

    prompt = f"""You write recruiting email invites for Accord Group (insurance restoration / project sales).

## Company context
{_company_context()}

## Candidate
{_candidate_context(candidate)}

## Requirements
- Address candidate as {fn}
- Invite to a ~30-minute phone screen for the {ROLE_TITLE} role
- Include this scheduling link on its own line: {calendly_url.strip()}
- Sign off as "Accord Group Recruiting"
- Add a brief compliance footer: reply UNSUBSCRIBE to stop recruiting messages
- Professional, warm, not overly long
- Do not invent compensation or guarantees not in context
{prev_block}
Return ONLY valid JSON (no markdown fences):
{{"subject": "...", "body": "..."}}"""

    try:
        raw = chat_completion(
            prompt=prompt,
            max_tokens=900,
            model=get_draft_model(),
            json_mode=True,
        ).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw).strip()
        data = json.loads(raw)
        subject = str(data.get("subject", "")).strip()
        body = str(data.get("body", "")).strip()
        if subject and body:
            return subject, body
    except (json.JSONDecodeError, RuntimeError):
        pass
    return template_redraft_r1_email(
        candidate,
        calendly_url,
        previous_subject=previous_subject,
        previous_body=previous_body,
    )
