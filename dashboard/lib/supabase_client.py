"""Supabase client for Accord recruiting dashboard."""

from __future__ import annotations

import os

import streamlit as st
from supabase import Client, create_client


def get_supabase() -> Client:
    url = _get_config("SUPABASE_URL")
    key = _get_config("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        st.error(
            "**Missing Supabase credentials.**\n\n"
            "**Streamlit Cloud:** open **Manage app → Settings → Secrets** and add:\n"
            "```toml\n"
            "SUPABASE_URL = \"https://kpbfjbnqvuwpceendzpv.supabase.co\"\n"
            "SUPABASE_SERVICE_ROLE_KEY = \"your_service_role_key\"\n"
            "```\n"
            "Then **Reboot app**.\n\n"
            "**Local:** copy `dashboard/.env.example` to `dashboard/.env` and add keys from "
            "[Supabase API settings](https://supabase.com/dashboard/project/kpbfjbnqvuwpceendzpv/settings/api)."
        )
        st.stop()
    return create_client(url, key)


def _get_config(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except (FileNotFoundError, KeyError):
        pass
    return os.getenv(name)
