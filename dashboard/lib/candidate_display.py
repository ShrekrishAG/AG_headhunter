"""Candidate avatar and resume helpers for the dashboard."""

from __future__ import annotations

import html
import re

import streamlit as st

from lib.avatar import initials_avatar_url
from lib.resume_slug import full_name_to_resume_slug


def linkedin_slug(linkedin_url: str | None) -> str | None:
    if not linkedin_url:
        return None
    match = re.search(r"linkedin\.com/in/([^/?#]+)", linkedin_url, re.I)
    if not match:
        return None
    return match.group(1).rstrip("/")


def candidate_avatar_url(candidate: dict, size: int = 128) -> str:
    if candidate.get("avatar_url"):
        return candidate["avatar_url"]
    return initials_avatar_url(candidate["full_name"], size)


def personal_network_contact(candidate: dict) -> str | None:
    value = candidate.get("personal_network_contact") or candidate.get("personal_reference_contact")
    if value and str(value).strip():
        return str(value).strip()
    return None


def has_personal_network(candidate: dict) -> bool:
    return personal_network_contact(candidate) is not None


def candidate_name_markdown(candidate: dict, *, level: int = 3) -> str:
    """Markdown heading with ★ prefix when candidate has a personal network contact."""
    prefix = "#" * level
    name = candidate["full_name"]
    if has_personal_network(candidate):
        return f"{prefix} ★ {name}"
    return f"{prefix} {name}"


def link_button_new_tab(label: str, url: str) -> None:
    """Render a full-width link styled like a Streamlit button, opening in a new tab."""
    st.markdown(
        f"""
<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer"
   style="text-decoration:none;display:block;width:100%;">
  <div style="
    display:flex;align-items:center;justify-content:center;width:100%;
    min-height:2.25rem;padding:0.25rem 0.75rem;margin-bottom:0.35rem;
    border:1px solid rgba(49,51,63,0.2);border-radius:0.5rem;
    background:#fff;color:#31333f;font-size:0.875rem;font-weight:400;
    box-sizing:border-box;cursor:pointer;">
    {html.escape(label)}
  </div>
</a>
""",
        unsafe_allow_html=True,
    )
