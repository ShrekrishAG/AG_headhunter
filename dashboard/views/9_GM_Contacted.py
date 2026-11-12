"""GM contacted — who managers marked on their packet checklists."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lib.constants import APP_NAME, get_selected_role_title
from lib.packet_checklist import (
    ChecklistStorageError,
    checklist_page_url,
    format_gm_contact_display,
    format_gm_interested_display,
    format_gm_not_interested_display,
    load_gm_contact_rows,
)
from lib.supabase_client import get_supabase

CT = ZoneInfo("America/Chicago")

st.title("GM contacted")
st.caption(
    f"{APP_NAME} · {get_selected_role_title()} · "
    "Candidates GMs marked on their checklist links (separate from pipeline Contacted)"
)

sb = get_supabase()
try:
    rows = load_gm_contact_rows(sb)
except ChecklistStorageError as exc:
    st.warning(str(exc))
    st.stop()

if not rows:
    st.info("No manager packet candidates logged yet. Send packets first.")
    st.stop()


def _to_ct_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(CT).date()
    except ValueError:
        return None


def _row_filter_date(row: dict, *, marked: bool) -> date | None:
    if marked:
        return _to_ct_date(
            row.get("gm_interested_at")
            or row.get("gm_contacted_at")
            or row.get("gm_not_interested_at")
        )
    return _to_ct_date(row.get("sent_at"))


def _is_unmarked(row: dict) -> bool:
    return (
        not row.get("gm_contacted_at")
        and not row.get("gm_interested_at")
        and not row.get("gm_not_interested_at")
    )


sent_dates = [d for d in (_to_ct_date(r.get("sent_at")) for r in rows) if d]
today = datetime.now(CT).date()
min_sent = min(sent_dates) if sent_dates else today
max_sent = max(sent_dates) if sent_dates else today

batches = sorted(
    {str(r.get("export_batch") or "") for r in rows if r.get("export_batch")},
    reverse=True,
)
markets = sorted({str(r.get("market") or "") for r in rows if r.get("market")})
managers = sorted(
    {str(r.get("manager_email") or "") for r in rows if r.get("manager_email")}
)

f1, f2, f3, f4 = st.columns([1.4, 1.2, 1.6, 1.4])
with f1:
    batch_filter = st.selectbox("Export batch", options=["All", *batches])
with f2:
    market_filter = st.selectbox("Market", options=["All", *markets])
with f3:
    manager_filter = st.selectbox("Manager", options=["All", *managers])
with f4:
    status_filter = st.radio(
        "Status",
        options=["All", "Contacted", "Interested", "Not interested", "Unmarked"],
        horizontal=True,
    )

d1, d2, d3, d4 = st.columns([1.2, 1.3, 1.1, 1.1])
with d1:
    date_field = st.radio(
        "Date is",
        options=["Packet sent", "GM marked"],
        horizontal=True,
        help=(
            "Packet sent = when the email went out. "
            "GM marked = when they checked Contacted, Interested, or Not interested."
        ),
    )
with d2:
    range_preset = st.selectbox(
        "Date range",
        options=["All dates", "Today", "Last 7 days", "Last 30 days", "Custom"],
    )
use_marked = date_field == "GM marked"
if range_preset == "Today":
    start_date, end_date = today, today
elif range_preset == "Last 7 days":
    start_date, end_date = today - timedelta(days=6), today
elif range_preset == "Last 30 days":
    start_date, end_date = today - timedelta(days=29), today
elif range_preset == "Custom":
    with d3:
        start_date = st.date_input("From (CT)", value=min_sent, min_value=min_sent, max_value=max(max_sent, today))
    with d4:
        end_date = st.date_input("To (CT)", value=max_sent, min_value=min_sent, max_value=max(max_sent, today))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
else:
    start_date, end_date = None, None

filtered = rows
if batch_filter != "All":
    filtered = [r for r in filtered if r.get("export_batch") == batch_filter]
if market_filter != "All":
    filtered = [r for r in filtered if r.get("market") == market_filter]
if manager_filter != "All":
    filtered = [r for r in filtered if r.get("manager_email") == manager_filter]
if status_filter == "Contacted":
    filtered = [r for r in filtered if r.get("gm_contacted_at")]
elif status_filter == "Interested":
    filtered = [r for r in filtered if r.get("gm_interested_at")]
elif status_filter == "Not interested":
    filtered = [r for r in filtered if r.get("gm_not_interested_at")]
elif status_filter == "Unmarked":
    filtered = [r for r in filtered if _is_unmarked(r)]
if start_date and end_date:
    kept = []
    for row in filtered:
        moment = _row_filter_date(row, marked=use_marked)
        if moment is None:
            continue
        if start_date <= moment <= end_date:
            kept.append(row)
    filtered = kept

contacted_n = sum(1 for r in filtered if r.get("gm_contacted_at"))
interested_n = sum(1 for r in filtered if r.get("gm_interested_at"))
ni_n = sum(1 for r in filtered if r.get("gm_not_interested_at"))
unmarked_n = sum(1 for r in filtered if _is_unmarked(r))
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("In view", len(filtered))
m2.metric("GM contacted", contacted_n)
m3.metric("Interested", interested_n)
m4.metric("Not interested", ni_n)
m5.metric("Unmarked", unmarked_n)
if start_date and end_date:
    st.caption(
        f"Showing {date_field} {start_date.strftime('%b %-d, %Y')} – "
        f"{end_date.strftime('%b %-d, %Y')} CT."
    )

# Summary by manager for the current filters
summary_map: dict[tuple[str, str], dict] = {}
for row in filtered:
    key = (str(row.get("market") or "—"), str(row.get("manager_email") or "—"))
    bucket = summary_map.get(key)
    if bucket is None:
        token = str(row.get("checklist_token") or "")
        bucket = {
            "Market": key[0],
            "Manager": key[1],
            "Contacted": 0,
            "Interested": 0,
            "Not interested": 0,
            "Candidates": 0,
            "Checklist": checklist_page_url(token) if token else "",
        }
        summary_map[key] = bucket
    bucket["Candidates"] += 1
    if row.get("gm_contacted_at"):
        bucket["Contacted"] += 1
    if row.get("gm_interested_at"):
        bucket["Interested"] += 1
    if row.get("gm_not_interested_at"):
        bucket["Not interested"] += 1

st.subheader("By manager")
if summary_map:
    summary_rows = sorted(summary_map.values(), key=lambda r: (r["Market"], r["Manager"]))
    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Checklist": st.column_config.LinkColumn("Checklist")},
    )

else:
    st.caption("No rows match these filters.")

st.subheader("Candidate list")
detail_rows = []
for row in filtered:
    if row.get("gm_interested_at"):
        status = "Interested"
        when = format_gm_interested_display(row.get("gm_interested_at"))
    elif row.get("gm_contacted_at"):
        status = "Contacted"
        when = format_gm_contact_display(row.get("gm_contacted_at"))
    elif row.get("gm_not_interested_at"):
        status = "Not interested"
        when = format_gm_not_interested_display(row.get("gm_not_interested_at"))
    else:
        status = "Unmarked"
        when = "—"
    sent = _to_ct_date(row.get("sent_at"))
    detail_rows.append(
        {
            "Status": status,
            "When marked": when,
            "Sent": sent.strftime("%b %-d, %Y") if sent else "—",
            "Name": row.get("candidate_name") or "—",
            "Phone": row.get("candidate_phone") or "—",
            "Email": row.get("candidate_email") or "—",
            "Market": row.get("market") or "—",
            "Manager": row.get("manager_email") or "—",
            "Batch": row.get("export_batch") or "—",
        }
    )

if detail_rows:
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
else:
    st.caption("No candidates match these filters.")
