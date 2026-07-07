"""Hiring process — Project Sales Representative (IdealTraits + resume rubric)."""

from __future__ import annotations

import streamlit as st

from lib.constants import APP_NAME, JOB_POSTING_URL, get_selected_role_slug, get_selected_role_title
from lib.job_description_dialog import request_job_description_dialog

st.title("Hiring process")
st.caption(f"{APP_NAME} · {get_selected_role_title()}")

if st.button("Job description", use_container_width=True):
    request_job_description_dialog(get_selected_role_slug())
st.link_button("IdealTraits posting", JOB_POSTING_URL, use_container_width=True)

st.divider()

st.markdown(
    f"""
**Project Sales Representative** — uncapped commission field sales at Accord Group.
Meet homeowners after storms, guide insurance restoration, control your pipeline and income.

**Salary range:** $60,000 – $175,000/year (commission-driven)  
**Source:** Primarily ZipRecruiter exports via `slack-zr-agent`
"""
)

st.subheader("Resume scoring (100-point rubric)")
st.markdown(
    """
Every resume is scored against the **Project Sales Rep Resume Scoring Rubric**:

| Score | Recommendation | Action |
|-------|----------------|--------|
| **85–100** | Strong interview | Prioritize for in-person interview |
| **70–84** | Good candidate | Interview if aligned with team needs |
| **60–69** | Phone screen | 5–10 min call first (IdealTraits process) |
| **Below 60** | Likely not a fit | Hold unless strong referral |

**Categories (100 pts):** Sales Experience (25) · Project/Field (20) · Customer Relationships (15) · Communication (15) · Technical/Tools (10) · Work Ethic (10) · minus Red Flags (up to 15)

See `roles/sales-representative/scorecard.md` and sample walkthrough (Jordan Martinez · 77 · Good candidate).
"""
)

st.subheader("Daily workflow")
st.markdown(
    """
1. Export candidates from ZipRecruiter via **slack-zr-agent**
2. Run import + sync:
   ```bash
   python scripts/import-ziprecruiter-export.py --latest
   python scripts/sync-candidates.py
   ```
3. Review **Pipeline** — each candidate shows **score /100** and **recommendation**
4. Advance Strong/Good candidates to phone screen → in-person interview
"""
)

st.subheader("IdealTraits interview path")
st.markdown(
    """
1. Apply on IdealTraits / ZipRecruiter
2. **5–10 minute phone call** — brief intro + role explanation
3. **In-person interview** at local Accord office
4. Offer + onboarding
"""
)

st.subheader("Using this dashboard")
st.markdown(
    """
- **Pipeline** — Ranked candidates with resume score, recommendation, and category breakdown
- **Job description** — Full role brief from IdealTraits posting
- **R1 Scoring** — Phone screen scorecards (Regional Manager + HR)
"""
)
