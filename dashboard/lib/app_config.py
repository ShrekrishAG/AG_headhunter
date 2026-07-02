"""Read dashboard config from Streamlit secrets or dashboard/.env."""

from __future__ import annotations

import os
from pathlib import Path

_DASHBOARD_ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_DASHBOARD_ROOT / ".env")
    except ImportError:
        pass


def get_config(name: str, default: str = "") -> str:
    load_env()
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError

        if st.secrets.load_if_toml_exists():
            value = st.secrets.get(name)
            if value:
                return str(value).strip()
    except (StreamlitSecretNotFoundError, FileNotFoundError, KeyError, AttributeError, ImportError):
        pass
    except Exception:
        pass
    return (os.getenv(name) or default).strip()
