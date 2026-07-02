"""App logo — st.logo in the sidebar header (expanded + collapsed)."""

from __future__ import annotations

import streamlit as st

from lib.constants import FAVICON_PATH, LOGO_PATH

LOGO_HEIGHT_EXPANDED_PX = 44
LOGO_HEIGHT_COLLAPSED_PX = 32


def configure_app_logo() -> None:
    """Render logo in the sidebar header; visible when sidebar is open or collapsed."""
    if not LOGO_PATH.exists():
        return

    icon = str(FAVICON_PATH if FAVICON_PATH.exists() else LOGO_PATH)
    st.logo(str(LOGO_PATH), icon_image=icon, size="large")
    st.markdown(
        f"""
<style>
/* Expanded sidebar — full portrait logo */
[data-testid="stSidebarHeader"] [data-testid="stLogo"] {{
  overflow: visible !important;
  padding: 0.35rem 0.5rem !important;
}}
[data-testid="stSidebarHeader"] [data-testid="stLogo"] img,
[data-testid="stSidebarHeader"] img[alt="Logo"] {{
  height: {LOGO_HEIGHT_EXPANDED_PX}px !important;
  width: auto !important;
  max-width: 100% !important;
  min-width: 28px !important;
  object-fit: contain !important;
}}

/* Collapsed sidebar — square icon beside the chevron (needs icon_image) */
[data-testid="stSidebarCollapsedControl"] [data-testid="stLogo"] img,
[data-testid="stSidebarCollapsedControl"] img[alt="Logo"] {{
  height: {LOGO_HEIGHT_COLLAPSED_PX}px !important;
  width: auto !important;
  max-width: {LOGO_HEIGHT_COLLAPSED_PX}px !important;
  min-width: 20px !important;
  object-fit: contain !important;
  border-radius: 0 !important;
}}
</style>
        """,
        unsafe_allow_html=True,
    )
