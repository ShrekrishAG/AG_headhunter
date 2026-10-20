"""GM contacted — who managers marked on their packet checklists."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.constants import APP_NAME, get_selected_role_title
from lib.packet_checklist import (
    ChecklistStorageError,
    checklist_page_url,
    format_gm_contact_display,
    format_gm_not_interested_display,
    load_gm_contact_rows,
)
from lib.supabase_client import get_supabase

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
        options=["All", "Contacted", "Not interested", "Unmarked"],
        horizontal=True,
    )

filtered = rows
if batch_filter != "All":
    filtered = [r for r in filtered if r.get("export_batch") == batch_filter]
if market_filter != "All":
    filtered = [r for r in filtered if r.get("market") == market_filter]
if manager_filter != "All":
    filtered = [r for r in filtered if r.get("manager_email") == manager_filter]
if status_filter == "Contacted":
    filtered = [r for r in filtered if r.get("gm_contacted_at")]
elif status_filter == "Not interested":
    filtered = [r for r in filtered if r.get("gm_not_interested_at")]
elif status_filter == "Unmarked":
    filtered = [
        r
        for r in filtered
        if not r.get("gm_contacted_at") and not r.get("gm_not_interested_at")
    ]

contacted_n = sum(1 for r in filtered if r.get("gm_contacted_at"))
ni_n = sum(1 for r in filtered if r.get("gm_not_interested_at"))
unmarked_n = sum(
    1
    for r in filtered
    if not r.get("gm_contacted_at") and not r.get("gm_not_interested_at")
)
m1, m2, m3, m4 = st.columns(4)
m1.metric("In view", len(filtered))
m2.metric("GM contacted", contacted_n)
m3.metric("Not interested", ni_n)
m4.metric("Unmarked", unmarked_n)

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
            "Not interested": 0,
            "Candidates": 0,
            "Checklist": checklist_page_url(token) if token else "",
        }
        summary_map[key] = bucket
    bucket["Candidates"] += 1
    if row.get("gm_contacted_at"):
        bucket["Contacted"] += 1
    if row.get("gm_not_interested_at"):
        bucket["Not interested"] += 1

st.subheader("By manager")
if summary_map:
    summary_df = pd.DataFrame(sorted(summary_map.values(), key=lambda r: (r["Market"], r["Manager"])))
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
    if row.get("gm_contacted_at"):
        status = "Contacted"
        when = format_gm_contact_display(row.get("gm_contacted_at"))
    elif row.get("gm_not_interested_at"):
        status = "Not interested"
        when = format_gm_not_interested_display(row.get("gm_not_interested_at"))
    else:
        status = "Unmarked"
        when = "—"
    detail_rows.append(
        {
            "Status": status,
            "When": when,
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
