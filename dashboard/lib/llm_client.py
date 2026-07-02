"""OpenAI LLM client for resume pre-screening and invite redrafts."""

from __future__ import annotations

import os
import time
from pathlib import Path

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_DRAFT_MODEL = "gpt-4o-mini"
MAX_RETRIES = 5
RETRY_BASE_SECONDS = 10

_DASHBOARD_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_DASHBOARD_ROOT / ".env")
    except ImportError:
        pass


def _get_config(name: str, default: str = "") -> str:
    _load_env()
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


def llm_configured() -> bool:
    return bool(_get_config("OPENAI_API_KEY"))


def get_draft_mode() -> str:
    """openai | template | auto (template when OpenAI unavailable)."""
    return (_get_config("REDRAFT_MODE") or "auto").strip().lower()


def redraft_available() -> bool:
    mode = get_draft_mode()
    if mode == "template":
        return True
    if mode == "openai":
        return llm_configured()
    return True  # auto — template fallback always available


def use_template_redraft() -> bool:
    mode = get_draft_mode()
    if mode == "template":
        return True
    if mode == "openai":
        return False
    return True  # auto: prefer template until OpenAI billing works


def openrouter_configured() -> bool:
    """Backward-compatible alias."""
    return llm_configured()


def get_prescreen_model() -> str:
    return _get_config("OPENAI_PRESCREEN_MODEL") or _get_config("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def get_draft_model() -> str:
    return (
        _get_config("OPENAI_DRAFT_MODEL")
        or _get_config("OPENAI_MODEL", DEFAULT_OPENAI_DRAFT_MODEL)
    )


def chat_completion(
    *,
    prompt: str,
    max_tokens: int = 2500,
    model: str | None = None,
    json_mode: bool = False,
) -> str:
    api_key = _get_config("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set — cannot run LLM tasks")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install openai: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    model_name = model or get_prescreen_model()
    last_error: Exception | None = None

    kwargs: dict = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("OpenAI returned empty message content")
            return content.strip()
        except Exception as exc:
            last_error = exc
            err = str(exc).lower()
            if "insufficient_quota" in err or "exceeded your current quota" in err:
                raise RuntimeError(
                    "OpenAI quota exceeded — add billing or credits at "
                    "https://platform.openai.com/settings/organization/billing"
                ) from exc
            if "429" in err or "rate" in err:
                wait = RETRY_BASE_SECONDS * (attempt + 1)
                print(f"    Rate limited — retry in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})", flush=True)
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"OpenAI failed after {MAX_RETRIES} retries: {last_error}")
