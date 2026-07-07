"""Shared sidebar: branding, logo, position selector, navigation."""

from __future__ import annotations

import streamlit as st

from lib.constants import (
    APP_NAME,
    LEGAL_NAME,
    LOGO_PATH,
    OPEN_ROLES,
    ROLE_SLUG,
)
from lib.job_description_dialog import request_job_description_dialog

def _inject_sidebar_layout_css() -> None:
    st.markdown(
        """
<style>
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 4rem);
}
[data-testid="stSidebar"] .accord-sidebar-push {
  flex: 1 1 auto;
  min-height: 1.5rem;
}
[data-testid="stSidebar"] .accord-sidebar-footer-logo img {
  max-width: 168px;
  width: 100%;
  height: auto;
  display: block;
  margin: 0 0 0.5rem 0;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def init_role_selection() -> None:
    if "role_slug" not in st.session_state:
        st.session_state.role_slug = ROLE_SLUG


def render_sidebar_branding() -> None:
    st.title(APP_NAME)
    st.caption(LEGAL_NAME)


def render_position_selector() -> str:
    titles = [role["title"] for role in OPEN_ROLES]
    slug_by_title = {role["title"]: role["slug"] for role in OPEN_ROLES}
    default_index = next(
        (i for i, role in enumerate(OPEN_ROLES) if role["slug"] == st.session_state.role_slug),
        0,
    )
    selected_title = st.selectbox(
        "Position",
        options=titles,
        index=default_index,
        key="position_selector",
    )
    st.session_state.role_slug = slug_by_title[selected_title]
    return st.session_state.role_slug


def render_sidebar_footer(*, communications_page, outreach_log_page) -> None:
    """Bottom-left: Accord logo + Communications / Outreach log."""
    st.markdown('<div class="accord-sidebar-push"></div>', unsafe_allow_html=True)
    st.divider()
    if LOGO_PATH.exists():
        st.markdown('<div class="accord-sidebar-footer-logo">', unsafe_allow_html=True)
        st.image(str(LOGO_PATH), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    st.page_link(communications_page, label="Communications", use_container_width=True)
    st.page_link(outreach_log_page, label="Outreach log", use_container_width=True)


def render_sidebar_nav(
    *,
    dashboard_page,
    process_page,
    communications_page,
    outreach_log_page,
    pipeline_page,
    r1_page,
) -> None:
    _inject_sidebar_layout_css()
    init_role_selection()
    render_sidebar_branding()
    role_slug = render_position_selector()
    st.divider()
    st.page_link(pipeline_page, label="Pipeline", use_container_width=True)
    st.page_link(dashboard_page, label="Dashboard", use_container_width=True)
    st.page_link(process_page, label="Process", use_container_width=True)
    if st.button("Job description", key="sidebar_job_description", use_container_width=True):
        request_job_description_dialog(role_slug)
    with st.expander("Interview Forms", expanded=True):
        st.page_link(r1_page, label="R1 Scoring", use_container_width=True)
    render_sidebar_footer(communications_page=communications_page, outreach_log_page=outreach_log_page)
