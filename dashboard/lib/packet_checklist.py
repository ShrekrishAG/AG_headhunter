"""Private checklist page for a GM packet, plus contact progress for Accord."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from supabase import Client

from lib.app_config import get_config

CT = ZoneInfo("America/Chicago")
CHECKLIST_MIGRATION = (
    "supabase/migrations/20261013120000_manager_packet_checklist.sql"
)
NOT_INTERESTED_MIGRATION = (
    "supabase/migrations/20261020120000_manager_packet_not_interested.sql"
)


class ChecklistStorageError(RuntimeError):
    pass


def public_checklist_token() -> str:
    raw = st.query_params.get("checklist")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def checklist_page_url(token: str) -> str:
    base = get_config(
        "STREAMLIT_APP_URL", "https://accord-headhunter.streamlit.app"
    ).rstrip("/")
    return f"{base}/?checklist={token}"


def checklist_storage_problem(sb: Client) -> str | None:
    """None when the checklist columns are ready. Otherwise a short reason."""
    try:
        sb.table("manager_packet_sends").select(
            "checklist_token,gm_contacted_at,gm_not_interested_at"
        ).limit(1).execute()
        return None
    except Exception as exc:
        text = str(exc).lower()
        if "gm_not_interested_at" in text:
            return (
                "GM checklist Not interested column is missing. Run "
                f"`{NOT_INTERESTED_MIGRATION}` in the Supabase SQL editor."
            )
        if (
            "checklist_token" in text
            or "gm_contacted_at" in text
            or "42703" in text
            or "does not exist" in text
        ):
            return (
                "GM checklist storage is not ready. Run "
                f"`{CHECKLIST_MIGRATION}` then `{NOT_INTERESTED_MIGRATION}` "
                "in the Supabase SQL editor."
            )
        return "Could not reach Supabase to load the checklist. Try again in a moment."


def checklist_storage_ready(sb: Client) -> bool:
    return checklist_storage_problem(sb) is None


def require_checklist_storage(sb: Client) -> None:
    problem = checklist_storage_problem(sb)
    if problem:
        raise ChecklistStorageError(problem)


def _format_marked_at(value: str | None, *, label: str) -> str:
    if not value:
        return ""
    text = str(value).replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text).astimezone(CT)
    except ValueError:
        return ""
    clock = moment.strftime("%b %-d, %-I:%M %p")
    return f"{label} {clock} CT"


def _format_contacted_at(value: str | None) -> str:
    return _format_marked_at(value, label="Marked contacted")


def _format_not_interested_at(value: str | None) -> str:
    return _format_marked_at(value, label="Marked not interested")


def load_checklist_rows(sb: Client, token: str) -> list[dict]:
    rows = (
        sb.table("manager_packet_sends")
        .select(
            "id,candidate_name,candidate_email,candidate_phone,market,"
            "manager_email,gm_contacted_at,gm_not_interested_at,checklist_token"
        )
        .eq("checklist_token", token)
        .execute()
        .data
        or []
    )
    return sorted(rows, key=lambda row: (row.get("candidate_name") or "").lower())


def set_gm_contacted(sb: Client, *, token: str, row_id: str, contacted: bool) -> None:
    payload: dict[str, str | None] = {
        "gm_contacted_at": datetime.now(CT).isoformat() if contacted else None,
    }
    if contacted:
        payload["gm_not_interested_at"] = None
    sb.table("manager_packet_sends").update(payload).eq("id", row_id).eq(
        "checklist_token", token
    ).execute()


def set_gm_not_interested(
    sb: Client, *, token: str, row_id: str, not_interested: bool
) -> None:
    payload: dict[str, str | None] = {
        "gm_not_interested_at": datetime.now(CT).isoformat() if not_interested else None,
    }
    if not_interested:
        payload["gm_contacted_at"] = None
    sb.table("manager_packet_sends").update(payload).eq("id", row_id).eq(
        "checklist_token", token
    ).execute()


def load_gm_contact_rows(sb: Client, *, limit: int = 2000) -> list[dict]:
    """All packet candidates with GM checklist status for the recruiting dashboard."""
    problem = checklist_storage_problem(sb)
    if problem:
        raise ChecklistStorageError(problem)
    rows = (
        sb.table("manager_packet_sends")
        .select(
            "candidate_name,candidate_email,candidate_phone,market,manager_email,"
            "export_batch,packet_id,checklist_token,gm_contacted_at,"
            "gm_not_interested_at,sent_at"
        )
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


def format_gm_contact_display(value: str | None) -> str:
    return _format_contacted_at(value).removeprefix("Marked contacted ").strip() or "—"


def format_gm_not_interested_display(value: str | None) -> str:
    return (
        _format_not_interested_at(value).removeprefix("Marked not interested ").strip()
        or "—"
    )


def load_batch_contact_progress(sb: Client, export_batch: str) -> list[dict]:
    problem = checklist_storage_problem(sb)
    if problem:
        raise ChecklistStorageError(problem)
    rows = (
        sb.table("manager_packet_sends")
        .select(
            "manager_email,market,packet_id,checklist_token,"
            "gm_contacted_at,gm_not_interested_at"
        )
        .eq("export_batch", export_batch)
        .execute()
        .data
        or []
    )
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row.get("manager_email") or ""), str(row.get("packet_id") or ""))
        bucket = grouped.get(key)
        if bucket is None:
            token = str(row.get("checklist_token") or "")
            bucket = {
                "Manager": key[0] or "—",
                "Market": row.get("market") or "—",
                "Contacted": 0,
                "Not interested": 0,
                "Candidates": 0,
                "Checklist": checklist_page_url(token) if token else "",
            }
            grouped[key] = bucket
        bucket["Candidates"] += 1
        if row.get("gm_contacted_at"):
            bucket["Contacted"] += 1
        if row.get("gm_not_interested_at"):
            bucket["Not interested"] += 1
    return sorted(grouped.values(), key=lambda item: (item["Market"], item["Manager"]))


def render_public_checklist(token: str) -> None:
    """Checklist for one GM. No dashboard login. Token is the only access."""
    st.markdown(
        """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="stHeader"] { display: none !important; }
.block-container { max-width: 720px; padding-top: 1.5rem; }
</style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Candidate checklist")
    if not token:
        st.error("This checklist link is missing a code.")
        return

    from lib.supabase_client import get_supabase

    sb = get_supabase()
    problem = checklist_storage_problem(sb)
    if problem:
        st.error(problem)
        return

    rows = load_checklist_rows(sb, token)
    if not rows:
        st.error("This checklist link is not valid.")
        return

    market = rows[0].get("market") or "your market"
    contacted = sum(1 for row in rows if row.get("gm_contacted_at"))
    not_interested = sum(1 for row in rows if row.get("gm_not_interested_at"))
    st.caption(
        f"{market} · {contacted} contacted · {not_interested} not interested · "
        f"{len(rows)} total. Mark each person after you talk to them. "
        "Accord can see what you mark."
    )

    for row in rows:
        row_id = str(row["id"])
        name = (row.get("candidate_name") or "Candidate").strip()
        st.markdown(f"**{name}**")
        phone = (row.get("candidate_phone") or "").strip()
        email = (row.get("candidate_email") or "").strip()
        bits = []
        if phone:
            bits.append(f"[{phone}](tel:{phone})")
        if email:
            bits.append(f"[{email}](mailto:{email})")
        when_contacted = _format_contacted_at(row.get("gm_contacted_at"))
        when_ni = _format_not_interested_at(row.get("gm_not_interested_at"))
        if when_contacted:
            bits.append(when_contacted)
        if when_ni:
            bits.append(when_ni)
        if bits:
            st.caption(" · ".join(bits))

        already_contacted = bool(row.get("gm_contacted_at"))
        already_ni = bool(row.get("gm_not_interested_at"))
        c1, c2 = st.columns(2)
        with c1:
            checked_contacted = st.checkbox(
                "Contacted",
                value=already_contacted,
                key=f"gm_contact_{row_id}",
            )
        with c2:
            checked_ni = st.checkbox(
                "Not interested",
                value=already_ni,
                key=f"gm_ni_{row_id}",
            )

        if checked_contacted != already_contacted:
            set_gm_contacted(
                sb, token=token, row_id=row_id, contacted=checked_contacted
            )
            st.rerun()
        if checked_ni != already_ni:
            set_gm_not_interested(
                sb, token=token, row_id=row_id, not_interested=checked_ni
            )
            st.rerun()
        st.divider()
