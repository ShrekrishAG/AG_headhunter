"""Outreach log — sent SMS and email records with candidate contact details."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lib.candidate_activity import (
    format_outreach_attempt,
    format_outreach_totals,
    load_outreach_log,
    tracking_available,
)
from lib.constants import (
    APP_NAME,
    PIPELINE_STAGES,
    get_selected_role_slug,
    get_selected_role_title,
)
from lib.supabase_client import get_supabase

CHICAGO = ZoneInfo("America/Chicago")
stage_labels = dict(PIPELINE_STAGES)

st.title("Outreach log")
st.caption(f"{APP_NAME} · {get_selected_role_title()} · SMS and email send records")

sb = get_supabase()
if not tracking_available(sb):
    st.warning(
        "Activity tracking is not set up yet. Run "
        "`python scripts/apply-activity-tracking-migration.py` and apply the SQL migration in Supabase."
    )
    st.stop()

roles = sb.table("roles").select("id, slug, title").execute().data
role = next((r for r in roles if r["slug"] == get_selected_role_slug()), roles[0])

filter_col, search_col = st.columns([1.2, 2])
with filter_col:
    channel_filter = st.radio(
        "Channel",
        options=["All", "SMS", "Email", "Failed only"],
        horizontal=True,
    )
with search_col:
    search = st.text_input("Search name, phone, or email", placeholder="e.g. Smith or +1816")

channel_arg = None
include_failed = True
if channel_filter == "SMS":
    channel_arg = "sms"
    include_failed = False
elif channel_filter == "Email":
    channel_arg = "email"
    include_failed = False
elif channel_filter == "Failed only":
    channel_arg = None
    include_failed = True
    # load_outreach_log with channel=None includes failed; filter below

rows = load_outreach_log(
    sb,
    role_id=role["id"],
    channel=channel_arg,
    include_failed=include_failed,
)

if channel_filter == "Failed only":
    rows = [r for r in rows if r["activity_type"] in ("sms_failed", "email_failed")]
elif channel_filter in ("SMS", "Email"):
    rows = [r for r in rows if r["activity_type"] in ("sms_sent", "email_sent")]

if search.strip():
    q = search.strip().lower()
    rows = [
        r
        for r in rows
        if q in (r.get("full_name") or "").lower()
        or q in (r.get("email") or "").lower()
        or q in (r.get("phone") or "").lower()
        or q in (r.get("to") or "").lower()
    ]


def _format_sent_at(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = dt.astimezone(CHICAGO)
        hour = local.strftime("%I").lstrip("0") or "12"
        return f"{local.strftime('%b %d, %Y')} · {hour}:{local.strftime('%M %p')} CT"
    except ValueError:
        return str(value)[:16]


def _channel_label(activity_type: str) -> str:
    if activity_type == "sms_sent":
        return "SMS"
    if activity_type == "email_sent":
        return "Email"
    if activity_type == "sms_failed":
        return "SMS failed"
    return "Email failed"


table_rows = []
for row in rows:
    activity_type = row.get("activity_type") or ""
    sms_total = int(row.get("sms_outreach_count") or 0)
    email_total = int(row.get("email_outreach_count") or 0)
    table_rows.append(
        {
            "Sent at": _format_sent_at(row.get("created_at")),
            "Name": row.get("full_name") or "—",
            "This attempt": format_outreach_attempt(
                activity_type, row.get("outreach_number")
            ),
            "Times reached": format_outreach_totals(sms_total, email_total),
            "Total touches": sms_total + email_total,
            "Phone": row.get("phone") or "—",
            "Email": row.get("email") or "—",
            "Channel": _channel_label(activity_type),
            "Sent to": row.get("to") or "—",
            "Subject": row.get("subject") or "—",
            "Message preview": row.get("body_preview") or row.get("error") or "—",
            "Bulk": "Yes" if row.get("bulk") else "",
            "Provider ID": row.get("external_id") or "—",
            "Stage": stage_labels.get(row.get("pipeline_stage"), row.get("pipeline_stage")),
            "Market": row.get("market") or "—",
        }
    )

sent_sms = sum(1 for r in rows if r.get("activity_type") == "sms_sent")
sent_email = sum(1 for r in rows if r.get("activity_type") == "email_sent")
failed = sum(1 for r in rows if r.get("activity_type") in ("sms_failed", "email_failed"))

m1, m2, m3, m4 = st.columns(4)
m1.metric("SMS sent", sent_sms)
m2.metric("Email sent", sent_email)
m3.metric("Failed", failed)
m4.metric("Showing", len(table_rows))

if not table_rows:
    st.info("No outreach records match your filters yet.")
    st.stop()

df = pd.DataFrame(table_rows)
st.dataframe(df, use_container_width=True, hide_index=True)

csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download CSV",
    data=csv,
    file_name=f"outreach-log-{role['slug']}.csv",
    mime="text/csv",
)

st.caption(
    "Each row is one send. **This attempt** is that channel’s sequence number at send time "
    "(e.g. SMS #2). **Times reached** is the candidate’s current SMS and email totals. "
    "Per-candidate timelines are also on Pipeline cards under **Activity timeline**."
)
