"""Shared constants for Accord Group Headhunter dashboard."""

import os
from pathlib import Path

APP_NAME = "Headhunter"
LEGAL_NAME = "Accord Group"
ORG_NAME = LEGAL_NAME

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = DASHBOARD_ROOT / "assets" / "accord-logo-dark.png"
FAVICON_PATH = DASHBOARD_ROOT / "assets" / "accord-favicon.png"
LOGO_SOURCE_URL = "https://weareaccord.com/wp-content/uploads/2023/03/Accord-Group-Logo.png"
LOGO_URL = LOGO_SOURCE_URL

ROLE_TITLE = "Project Sales Representative"
ROLE_SLUG = "sales-representative"
RESUME_ROLE_PREFIX = "sales-rep"
JOB_POSTING_URL = (
    "https://app.idealtraits.com/career/Accord-Group-Inc./350124CPGG12"
)

OPEN_ROLES = [
    {"slug": "sales-representative", "title": "Project Sales Representative"},
]

STREAMLIT_APP_URL = os.getenv(
    "STREAMLIT_APP_URL", "https://accord-headhunter.streamlit.app"
).rstrip("/")

PAGE_PATHS = {
    "Pipeline": "",
    "Dashboard": "dashboard",
    "Process": "process",
    "Job description": "job-description",
    "R1 Scoring": "r1-scoring",
}


def page_url(path: str) -> str:
    return f"{STREAMLIT_APP_URL}/{path}" if path else f"{STREAMLIT_APP_URL}/"


JOB_DESCRIPTION_URL = page_url("job-description")

# Project Sales Rep resume rubric (100 points) — see roles/sales-representative/scorecard.md
RUBRIC_CATEGORIES = [
    {
        "label": "Sales Experience",
        "max_points": 25,
        "hint": "3+ years B2B/home services/field sales; prospecting, closing, CRM, quota wins",
    },
    {
        "label": "Project / Field Experience",
        "max_points": 20,
        "hint": "Projects/installations/repairs; scope customer needs; site visits & proposals",
    },
    {
        "label": "Customer Relationship Skills",
        "max_points": 15,
        "hint": "Consultative selling, objection handling, trust-building",
    },
    {
        "label": "Communication & Professionalism",
        "max_points": 15,
        "hint": "Clear resume, measurable outcomes, reliability",
    },
    {
        "label": "Technical / Tool Fit",
        "max_points": 10,
        "hint": "CRM (Salesforce, JobNimbus, ServiceTitan, etc.), mobile/tablet tools",
    },
    {
        "label": "Work Ethic & Culture Fit Signals",
        "max_points": 10,
        "hint": "Self-motivation, commission/field roles, teamwork",
    },
]

RED_FLAG_MAX_DEDUCTION = 15

SCORE_BANDS = [
    (85, "Strong interview"),
    (70, "Good candidate"),
    (55, "Phone screen"),
    (0, "Likely not a fit"),
]

QUALIFIED_MIN_SCORE = 70

# Legacy R1 phone-screen dimensions (1–4) — kept for interviewer scorecards
SCORE_LABELS = {
    1: "1 — Pass",
    2: "2 — Possible",
    3: "3 — Strong",
    4: "4 — Exceptional",
}

DIMENSIONS = [
    {
        "score_key": "score_sales_track_record",
        "evidence_key": "evidence_sales_track_record",
        "label": "Sales track record",
        "weight": 0.25,
        "hint": "Quota attainment, revenue growth, or documented sales wins",
    },
    {
        "score_key": "score_communication",
        "evidence_key": "evidence_communication",
        "label": "Communication & rapport",
        "weight": 0.20,
        "hint": "Clear communicator; builds trust with homeowners and teammates",
    },
    {
        "score_key": "score_work_ethic",
        "evidence_key": "evidence_work_ethic",
        "label": "Work ethic & discipline",
        "weight": 0.20,
        "hint": "Self-starter, consistent follow-through, positive attitude",
    },
    {
        "score_key": "score_market_fit",
        "evidence_key": "evidence_market_fit",
        "label": "Local market fit",
        "weight": 0.15,
        "hint": "Local ties, territory knowledge, willingness to work assigned market",
    },
    {
        "score_key": "score_leadership_potential",
        "evidence_key": "evidence_leadership_potential",
        "label": "Leadership potential",
        "weight": 0.10,
        "hint": "Team player who can mentor others and grow with the company",
    },
    {
        "score_key": "score_culture_fit",
        "evidence_key": "evidence_culture_fit",
        "label": "Culture & values fit",
        "weight": 0.10,
        "hint": "Integrity, Golden Rule, humility — aligned with Accord values",
    },
]

GATES = [
    ("gate_valid_license", "Valid driver's license and full-time access to a vehicle"),
    ("gate_us_work_auth", "Authorized to work in the United States"),
    ("gate_travel", "Able to travel if the job requires"),
    ("gate_market_willingness", "Willing to work in the assigned market/territory"),
]

AGENT_GATE_KEYS = [
    "valid_license",
    "us_work_auth",
    "can_travel",
    "market_willingness",
]

INTERVIEWERS = {
    "regional_manager": "Regional Manager",
    "recruiter": "HR / Recruiter",
}

VOTES = {
    "advance": "Advance",
    "hold": "Hold",
    "pass": "Pass",
}

PIPELINE_STAGES = [
    ("identified", "Awaiting / below threshold"),
    ("qualified", "Resume qualified"),
    ("outreached", "Outreached (invite sent)"),
    ("round_1_scheduled", "Phone screen scheduled"),
    ("round_1_complete", "Phone screen complete"),
    ("round_2_scheduled", "In-person scheduled"),
    ("round_2_complete", "In-person complete"),
    ("offer", "Offer"),
    ("closed", "Closed"),
]

STAGE_ORDER = [s[0] for s in PIPELINE_STAGES]

OUTREACH_STAGE = "outreached"

# Stages at or past confirmed phone screen — outreach sends do not change these.
STAGES_AT_OR_PAST_PHONE_SCHEDULED = frozenset(
    {
        "round_1_scheduled",
        "round_1_complete",
        "round_2_scheduled",
        "round_2_complete",
        "offer",
        "closed",
    }
)

PIPELINE_DISPLAY_ORDER = [
    "qualified",
    "outreached",
    "identified",
    *[s for s in STAGE_ORDER if s not in ("qualified", "identified", "outreached")],
]

SOURCES = [
    "ZipRecruiter",
    "Indeed",
    "LinkedIn",
    "Referral",
    "Personal network",
    "Walk-in",
    "Other",
]

DEFAULT_OWNER = "Accord Recruiting"

# R1 phone-screen scorecard (1–4 weighted scale) — separate from resume rubric
R1_RECOMMEND_THRESHOLD = 3.2
R1_CONSIDER_THRESHOLD = 3.0


def role_title_for_slug(slug: str) -> str:
    for role in OPEN_ROLES:
        if role["slug"] == slug:
            return role["title"]
    return slug


def get_selected_role_slug() -> str:
    import streamlit as st

    return st.session_state.get("role_slug", ROLE_SLUG)


def get_selected_role_title() -> str:
    return role_title_for_slug(get_selected_role_slug())


def interviewer_keys() -> list[str]:
    return list(INTERVIEWERS.keys())
