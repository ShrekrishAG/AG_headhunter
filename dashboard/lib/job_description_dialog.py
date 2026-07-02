"""Modal job description viewer/editor for the selected position."""

from __future__ import annotations

import streamlit as st

from lib.constants import JOB_POSTING_URL, ROLE_SLUG, role_title_for_slug
from lib.role_brief import load_role_brief, role_brief_path, save_role_brief

JD_DIALOG_OPEN_KEY = "jd_dialog_open"
JD_DIALOG_ROLE_KEY = "jd_dialog_role"


def _edit_mode_key(role_slug: str) -> str:
    return f"jd_edit_mode_{role_slug}"


def _draft_key(role_slug: str) -> str:
    return f"jd_draft_{role_slug}"


def request_job_description_dialog(role_slug: str) -> None:
    """Keep dialog open across reruns (e.g. Edit / Save inside the modal)."""
    st.session_state[JD_DIALOG_OPEN_KEY] = True
    st.session_state[JD_DIALOG_ROLE_KEY] = role_slug


def close_job_description_dialog() -> None:
    role_slug = st.session_state.get(JD_DIALOG_ROLE_KEY)
    if role_slug:
        st.session_state.pop(_edit_mode_key(role_slug), None)
        st.session_state.pop(_draft_key(role_slug), None)
    st.session_state[JD_DIALOG_OPEN_KEY] = False
    st.session_state.pop(JD_DIALOG_ROLE_KEY, None)


def maybe_show_job_description_dialog() -> None:
    if not st.session_state.get(JD_DIALOG_OPEN_KEY):
        return
    role_slug = st.session_state.get(JD_DIALOG_ROLE_KEY) or ROLE_SLUG
    open_job_description_dialog(role_slug)


@st.dialog("Job description", width="large", on_dismiss=close_job_description_dialog)
def open_job_description_dialog(role_slug: str) -> None:
    title = role_title_for_slug(role_slug)
    st.markdown(f"### {title}")
    st.link_button("View on IdealTraits", JOB_POSTING_URL, use_container_width=True)

    st.info(
        "The **resume pre-screen agent** reads this file (`roles/…/brief.md`) plus "
        "`scorecard.md` (100-point rubric) and `sample-walkthrough.md` when scoring candidates. "
        "Editing here updates future pre-screens; already-scored profiles are unchanged until re-run."
    )

    brief_path = role_brief_path(role_slug)
    if not brief_path.is_file():
        st.error(f"Job description file not found for role `{role_slug}`.")
        return

    edit_mode = st.session_state.get(_edit_mode_key(role_slug), False)
    _, edit_col = st.columns([4, 1])
    with edit_col:
        if st.button("Edit" if not edit_mode else "Cancel", key=f"jd_toggle_{role_slug}"):
            st.session_state[_edit_mode_key(role_slug)] = not edit_mode
            if edit_mode:
                st.session_state.pop(_draft_key(role_slug), None)

    content = load_role_brief(role_slug)

    if edit_mode:
        draft = st.text_area(
            "Edit job description (Markdown)",
            value=st.session_state.get(_draft_key(role_slug), content),
            height=420,
            key=f"jd_editor_{role_slug}",
            label_visibility="collapsed",
        )
        st.session_state[_draft_key(role_slug)] = draft
        save_col, _ = st.columns([1, 3])
        with save_col:
            if st.button("Save changes", type="primary", key=f"jd_save_{role_slug}"):
                save_role_brief(role_slug, draft)
                st.session_state[_edit_mode_key(role_slug)] = False
                st.session_state.pop(_draft_key(role_slug), None)
                st.success("Job description saved.")
        st.caption(
            "Saves to the repo file on this machine. Commit to git for team-wide / deployed updates."
        )
    else:
        st.divider()
        st.markdown(content)
