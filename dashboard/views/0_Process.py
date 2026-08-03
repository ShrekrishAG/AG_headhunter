"""Hiring process — role-aware (sidebar Position)."""

from __future__ import annotations

import streamlit as st

from lib.constants import (
    APP_NAME,
    RED_FLAG_MAX_DEDUCTION,
    get_selected_role_slug,
    get_selected_role_title,
    job_posting_url_for_slug,
    qualified_min_score_for_slug,
    role_rubric_for_slug,
    rubric_categories_for_slug,
)
from lib.job_description_dialog import request_job_description_dialog

ROLE_OVERVIEW = {
    "sales-representative": {
        "blurb": (
            "**Project Sales Representative** — uncapped commission field sales at "
            "Accord Group. Meet homeowners after storms, guide insurance restoration, "
            "control your pipeline and income."
        ),
        "salary": "$60,000 – $175,000/year (commission-driven)",
        "source": "Primarily ZipRecruiter exports via `slack-zr-agent`",
        "rubric_name": "Project Sales Rep Resume Scoring Rubric",
        "sample": "Jordan Martinez · 77 · Good candidate",
        "workflow": """
1. Export candidates from ZipRecruiter via **slack-zr-agent**
2. Run import + sync:
   ```bash
   python scripts/import-ziprecruiter-export.py --latest
   python scripts/sync-candidates.py
   ```
3. Review **Pipeline** — each candidate shows **score /100** and **recommendation**
4. Advance Strong/Good candidates to phone screen → in-person interview
""",
        "interview_path": """
1. Apply on IdealTraits / ZipRecruiter
2. **5–10 minute phone call** — brief intro + role explanation
3. **In-person interview** at local Accord office
4. Offer + onboarding
""",
    },
    "general-manager": {
        "blurb": (
            "**General Manager (Roofing / Sales)** — hands-on location leadership "
            "as Managing Partner / GM. Hire and coach the team, own sales goals, "
            "operations, and P&L — path to multi-unit leadership."
        ),
        "salary": "Successful GMs / Managing Partners earn $200K+ annually",
        "source": (
            "IdealTraits posting, referrals, and **Import prospects** "
            "(CSV + optional resumes)"
        ),
        "rubric_name": "Roofing General / Sales Manager Resume Scoring Rubric",
        "sample": "Alex Rivera · 82 · Good candidate",
        "workflow": """
1. Source candidates (IdealTraits, referrals, LinkedIn) or use **Import prospects**
2. Score resumes against the GM rubric (or skip if no resume / LinkedIn text)
3. Review **Pipeline** — qualified bar is higher than Sales Rep (**≥ 70**)
4. Advance Strong/Good candidates to IdealTraits assessment → leadership interview
""",
        "interview_path": """
1. Apply via IdealTraits
2. Assessment + brief questionnaire (including short video answers)
3. First interview after evaluation — discuss next steps
4. Offer + onboarding / MIT path as applicable
""",
    },
}

role_slug = get_selected_role_slug()
role_title = get_selected_role_title()
overview = ROLE_OVERVIEW.get(role_slug, ROLE_OVERVIEW["sales-representative"])
categories = rubric_categories_for_slug(role_slug)
qualified_min = qualified_min_score_for_slug(role_slug)
posting_url = job_posting_url_for_slug(role_slug)
bands = role_rubric_for_slug(role_slug).get("score_bands") or []

st.title("Hiring process")
st.caption(f"{APP_NAME} · {role_title}")

if st.button("Job description", use_container_width=True):
    request_job_description_dialog(role_slug)
st.link_button("IdealTraits posting", posting_url, use_container_width=True)

st.divider()

st.markdown(
    f"""
{overview["blurb"]}

**Salary range:** {overview["salary"]}  
**Source:** {overview["source"]}  
**Pipeline qualify:** score **≥ {qualified_min}**
"""
)

st.subheader("Resume scoring (100-point rubric)")

band_rows = []
# SCORE_BANDS are (min_score, label) descending — rebuild display ranges
sorted_bands = sorted(bands, key=lambda b: b[0], reverse=True)
for i, (min_score, label) in enumerate(sorted_bands):
    if i == 0:
        rng = f"**{min_score}–100**"
    else:
        prev_min = sorted_bands[i - 1][0]
        upper = prev_min - 1
        if min_score == 0:
            rng = f"**Below {upper + 1}**"
        else:
            rng = f"**{min_score}–{upper}**"
    action = {
        "Strong interview": "Prioritize for interview",
        "Good candidate": "Interview if aligned with team needs",
        "Phone screen": "Short screen first (IdealTraits process)",
        "Likely not a fit": "Hold unless strong referral",
    }.get(label, "")
    band_rows.append(f"| {rng} | {label} | {action} |")

category_line = " · ".join(f"{c['label']} ({c['max_points']})" for c in categories)

st.markdown(
    f"""
Every resume is scored against the **{overview["rubric_name"]}**:

| Score | Recommendation | Action |
|-------|----------------|--------|
{chr(10).join(band_rows)}

**Categories (100 pts):** {category_line} · minus Red Flags (up to {RED_FLAG_MAX_DEDUCTION})

See `roles/{role_slug}/scorecard.md` and sample walkthrough ({overview["sample"]}).
"""
)

st.subheader("Daily workflow")
st.markdown(overview["workflow"])

st.subheader("IdealTraits interview path")
st.markdown(overview["interview_path"])

st.subheader("Using this dashboard")
st.markdown(
    """
- **Pipeline** — Ranked candidates with resume score, recommendation, and category breakdown
- **Import prospects** — CSV + resume import for non-ZipRecruiter leads
- **Job description** — Full role brief from IdealTraits posting (follows sidebar Position)
- **R1 Scoring** — Phone screen scorecards (Regional Manager + HR)
"""
)
