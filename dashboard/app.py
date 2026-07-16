"""Accord Group Headhunter — Streamlit recruiting dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from lib.branding import configure_app_logo  # noqa: E402
from lib.constants import APP_NAME, FAVICON_PATH, LOGO_PATH  # noqa: E402
from lib.sidebar import render_sidebar_nav  # noqa: E402
from lib.job_description_dialog import maybe_show_job_description_dialog  # noqa: E402

_icon_path = FAVICON_PATH if FAVICON_PATH.exists() else LOGO_PATH
st.set_page_config(
    page_title=f"{APP_NAME} · Recruiting",
    page_icon=str(_icon_path) if _icon_path.exists() else "💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

configure_app_logo()

# views/ (not pages/) — Streamlit assumes legacy multipage routing for a pages/ folder
# and shows a false "Page not found" modal on direct URLs before st.navigation() runs.
VIEWS = "views"

dashboard_page = st.Page(
    f"{VIEWS}/4_Dashboard.py",
    title="Dashboard",
    url_path="dashboard",
)
process_page = st.Page(f"{VIEWS}/0_Process.py", title="Process", url_path="process")
communications_page = st.Page(
    f"{VIEWS}/5_Communications_Setup.py",
    title="Communications",
    url_path="communications",
)
outreach_log_page = st.Page(
    f"{VIEWS}/6_Outreach_Log.py",
    title="Outreach log",
    url_path="outreach-log",
)
manager_packets_page = st.Page(
    f"{VIEWS}/7_Manager_Packets.py",
    title="Manager packets",
    url_path="manager-packets",
)
pipeline_page = st.Page(
    f"{VIEWS}/2_Pipeline_Report.py",
    title="Pipeline",
    url_path="",
    default=True,
)
r1_page = st.Page(f"{VIEWS}/1_R1_Scoring.py", title="R1 Scoring", url_path="r1-scoring")
job_description_page = st.Page(
    f"{VIEWS}/3_Job_Description.py",
    title="Job Description",
    url_path="job-description",
)

# Legacy multipage URLs (bookmarks from before st.navigation url_path routes).
legacy_pages = [
    st.Page(f"{VIEWS}/4_Dashboard.py", title="Dashboard", url_path="4_Dashboard"),
    st.Page(f"{VIEWS}/0_Process.py", title="Process", url_path="0_Process"),
    st.Page(f"{VIEWS}/5_Communications_Setup.py", title="Communications", url_path="5_Communications_Setup"),
    st.Page(f"{VIEWS}/6_Outreach_Log.py", title="Outreach log", url_path="6_Outreach_Log"),
    st.Page(f"{VIEWS}/7_Manager_Packets.py", title="Manager packets", url_path="7_Manager_Packets"),
    st.Page(f"{VIEWS}/2_Pipeline_Report.py", title="Pipeline", url_path="2_Pipeline_Report"),
    st.Page(f"{VIEWS}/3_Job_Description.py", title="Job Description", url_path="3_Job_Description"),
    st.Page(f"{VIEWS}/1_R1_Scoring.py", title="R1 Scoring", url_path="1_R1_Scoring"),
]

pg = st.navigation(
    {
        "": [
            pipeline_page,
            dashboard_page,
            manager_packets_page,
            process_page,
            job_description_page,
            *legacy_pages,
        ],
        "Interview Forms": [r1_page],
        "Settings": [communications_page, outreach_log_page],
    },
    position="hidden",
)

with st.sidebar:
    render_sidebar_nav(
        dashboard_page=dashboard_page,
        process_page=process_page,
        communications_page=communications_page,
        outreach_log_page=outreach_log_page,
        manager_packets_page=manager_packets_page,
        pipeline_page=pipeline_page,
        r1_page=r1_page,
    )

pg.run()
maybe_show_job_description_dialog()
