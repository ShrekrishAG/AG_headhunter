"""Dashboard login gate — username/password from secrets / .env."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import unquote

import extra_streamlit_components as stx
import streamlit as st

from lib.app_config import get_config
from lib.constants import APP_NAME, LEGAL_NAME, LOGO_PATH

AUTH_USER_KEY = "auth_user"
AUTH_NAME_KEY = "auth_display_name"
_AUTH_COOKIE_ACTION_KEY = "_auth_cookie_action"

REMEMBER_COOKIE = "hh_remember"
REMEMBER_DAYS = 30

# pbkdf2$iterations$salt_hex$hash_hex
_HASH_RE = re.compile(r"^pbkdf2\$(\d+)\$([0-9a-f]+)\$([0-9a-f]+)$", re.I)
_PBKDF2_ITERATIONS = 260_000

@dataclass(frozen=True)
class AuthUser:
    username: str
    name: str
    password_plain: str | None = None
    password_hash: str | None = None


def auth_enabled() -> bool:
    raw = get_config("HEADHUNTER_AUTH_ENABLED", "true").lower()
    return raw in ("1", "true", "yes", "on")


def hash_password(password: str, *, salt_hex: str | None = None) -> str:
    """Create a pbkdf2 password hash string for HEADHUNTER_USERS."""
    import secrets

    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, user: AuthUser) -> bool:
    if user.password_hash:
        match = _HASH_RE.match(user.password_hash.strip())
        if not match:
            return False
        iterations = int(match.group(1))
        salt = bytes.fromhex(match.group(2))
        expected = bytes.fromhex(match.group(3))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    if user.password_plain is not None:
        return hmac.compare_digest(password, user.password_plain)
    return False


def _parse_users_json(raw: str) -> list[AuthUser]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("HEADHUNTER_USERS must be a JSON list")
    users: list[AuthUser] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip().lower()
        name = str(item.get("name") or username).strip()
        password_hash = item.get("password_hash")
        password = item.get("password")
        if not username:
            continue
        if password_hash:
            users.append(
                AuthUser(
                    username=username,
                    name=name,
                    password_hash=str(password_hash).strip(),
                )
            )
        elif password is not None and str(password) != "":
            users.append(
                AuthUser(
                    username=username,
                    name=name,
                    password_plain=str(password),
                )
            )
    return users


def _parse_users_delimited(raw: str) -> list[AuthUser]:
    """Format: username|Display Name|password ; username|Name|password"""
    users: list[AuthUser] = []
    for chunk in re.split(r"[;\n]+", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) < 2:
            continue
        username = parts[0].lower()
        if len(parts) == 2:
            name, secret = username, parts[1]
        else:
            name, secret = parts[1], parts[2]
        if not username or not secret:
            continue
        if secret.startswith("pbkdf2$"):
            users.append(AuthUser(username=username, name=name, password_hash=secret))
        else:
            users.append(AuthUser(username=username, name=name, password_plain=secret))
    return users


def load_auth_users() -> list[AuthUser]:
    raw = get_config("HEADHUNTER_USERS")
    if not raw:
        return []
    raw = raw.strip()
    # Streamlit Secrets often wraps JSON in """ with leading newlines
    if raw.startswith("["):
        return _parse_users_json(raw)
    return _parse_users_delimited(raw)


def _auth_signing_key() -> bytes:
    secret = (
        get_config("HEADHUNTER_AUTH_SECRET")
        or get_config("HEADHUNTER_USERS")
        or "headhunter-dev-auth"
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _make_remember_token(username: str, *, days: int = REMEMBER_DAYS) -> str:
    exp = int(time.time()) + max(1, days) * 86_400
    payload = f"{username.strip().lower()}:{exp}"
    sig = hmac.new(_auth_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _parse_remember_token(token: str | None) -> str | None:
    raw = unquote((token or "").strip())
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    username, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    payload = f"{username}:{exp}"
    expected = hmac.new(
        _auth_signing_key(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return username.strip().lower() or None


def _cookie_manager() -> stx.CookieManager:
    return stx.CookieManager(key="hh_auth_cookie_manager")


def _read_remember_cookie(cm: stx.CookieManager) -> str | None:
    token = cm.get(REMEMBER_COOKIE)
    if not token:
        try:
            token = st.context.cookies.get(REMEMBER_COOKIE)
        except Exception:
            token = None
    return _parse_remember_token(str(token) if token is not None else None)


def _queue_remember_cookie(token: str | None, *, days: int = REMEMBER_DAYS) -> None:
    st.session_state[_AUTH_COOKIE_ACTION_KEY] = {"token": token, "days": days}


def _apply_remember_cookie_action(cm: stx.CookieManager) -> None:
    action = st.session_state.pop(_AUTH_COOKIE_ACTION_KEY, None)
    if not action:
        return
    token = action.get("token")
    days = int(action.get("days") or REMEMBER_DAYS)
    # Unique Streamlit keys so set/delete can run more than once per session
    stamp = str(int(time.time() * 1000))
    if token:
        expires_at = datetime.now() + timedelta(days=max(1, days))
        cm.set(
            REMEMBER_COOKIE,
            token,
            key=f"hh_remember_set_{stamp}",
            expires_at=expires_at,
            same_site="lax",
        )
    else:
        try:
            cm.delete(REMEMBER_COOKIE, key=f"hh_remember_del_{stamp}")
        except KeyError:
            # Cookie already absent — ignore so login page still loads.
            pass


def _restore_from_remember_cookie(cm: stx.CookieManager) -> bool:
    username = _read_remember_cookie(cm)
    if not username:
        return False
    for user in load_auth_users():
        if user.username == username:
            login_user(user.username, user.name)
            return True
    # Stale cookie for removed user
    _queue_remember_cookie(None)
    return False


def is_authenticated() -> bool:
    return bool(st.session_state.get(AUTH_USER_KEY))


def current_user() -> str | None:
    return st.session_state.get(AUTH_USER_KEY)


def current_display_name() -> str:
    return st.session_state.get(AUTH_NAME_KEY) or current_user() or ""


def login_user(username: str, display_name: str) -> None:
    st.session_state[AUTH_USER_KEY] = username
    st.session_state[AUTH_NAME_KEY] = display_name


def logout_user() -> None:
    st.session_state.pop(AUTH_USER_KEY, None)
    st.session_state.pop(AUTH_NAME_KEY, None)
    _queue_remember_cookie(None)


def try_login(
    username: str, password: str, *, remember_me: bool = False
) -> tuple[bool, str]:
    users = load_auth_users()
    if not users:
        return False, "No users configured. Set HEADHUNTER_USERS in secrets / .env."
    key = (username or "").strip().lower()
    if not key or not password:
        return False, "Enter email and password."
    for user in users:
        if user.username == key and verify_password(password, user):
            login_user(user.username, user.name)
            if remember_me:
                _queue_remember_cookie(_make_remember_token(user.username))
            else:
                _queue_remember_cookie(None)
            return True, ""
    return False, "Invalid email or password."


def render_login_page(cm: stx.CookieManager | None = None) -> None:
    """Full-page login; call st.stop() after this when unauthenticated."""
    if cm is None:
        cm = _cookie_manager()
        _apply_remember_cookie_action(cm)
    col_l, col_m, col_r = st.columns([1, 1.2, 1])
    with col_m:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), use_container_width=True)
        st.title(f"{APP_NAME}")
        st.caption(f"{LEGAL_NAME} · Sign in to continue")

        users = load_auth_users()
        if not users:
            st.error(
                "Login is enabled but no users are configured. "
                "Add `HEADHUNTER_USERS` to `dashboard/.env` or Streamlit secrets."
            )
            st.code(
                'HEADHUNTER_USERS=[{"username":"you@company.com","name":"Your Name","password":"choose-a-strong-password"}]',
                language="bash",
            )
            return

        with st.form("headhunter_login"):
            username = st.text_input("Email", autocomplete="username")
            password = st.text_input(
                "Password", type="password", autocomplete="current-password"
            )
            remember_me = st.checkbox("Remember me for 30 days", value=False)
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            ok, err = try_login(username, password, remember_me=remember_me)
            if ok:
                st.rerun()
            st.error(err)


def require_login() -> bool:
    """
    Gate the app. Returns True if the user may continue.
    When False, the login UI was shown — caller should st.stop().
    """
    if not auth_enabled():
        return True

    cm = _cookie_manager()
    _apply_remember_cookie_action(cm)

    if is_authenticated():
        return True
    if _restore_from_remember_cookie(cm):
        _apply_remember_cookie_action(cm)
        return True
    render_login_page(cm)
    return False


def render_sidebar_auth() -> None:
    """Show signed-in user + logout in the sidebar."""
    if not auth_enabled() or not is_authenticated():
        return
    st.caption(f"Signed in as **{current_display_name()}**")
    if st.button("Log out", use_container_width=True, key="auth_logout"):
        logout_user()
        st.rerun()
