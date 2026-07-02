"""Recruiting dashboard — applies by day and source."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.constants import APP_NAME, PIPELINE_STAGES, get_selected_role_slug, get_selected_role_title
from lib.supabase_client import get_supabase

st.title("Dashboard")
st.caption(f"{APP_NAME} · {get_selected_role_title()}")

sb = get_supabase()
role_slug = get_selected_role_slug()

roles = sb.table("roles").select("id, slug, title").execute().data
role = next((r for r in roles if r["slug"] == role_slug), roles[0])

candidates = (
    sb.table("candidates")
    .select(
        "id, full_name, source, pipeline_stage, created_at, "
        "sms_outreach_count, email_outreach_count, last_activity_at"
    )
    .eq("role_id", role["id"])
    .order("created_at")
    .execute()
    .data
)

if not candidates:
    st.info("No applicants yet for this position.")
    st.stop()

df = pd.DataFrame(candidates)
df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
df["apply_date"] = df["created_at"].dt.tz_convert("America/Chicago").dt.date
df["source"] = df["source"].fillna("Unknown")

stage_labels = dict(PIPELINE_STAGES)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total applicants", len(df))
m2.metric("Agent qualified", int((df["pipeline_stage"] == "qualified").sum()))
m3.metric("Outreached", int((df["pipeline_stage"] == "outreached").sum()))
m4.metric("Agent pass", int((df["pipeline_stage"] == "identified").sum()))

if "sms_outreach_count" in df.columns and "email_outreach_count" in df.columns:
    sms = df["sms_outreach_count"].fillna(0)
    email = df["email_outreach_count"].fillna(0)
    contacted = int(((sms > 0) | (email > 0)).sum())
    qualified_uncontacted = int(
        ((df["pipeline_stage"] == "qualified") & (sms <= 0) & (email <= 0)).sum()
    )
else:
    contacted = 0
    qualified_uncontacted = 0

m5, m6 = st.columns(2)
m5.metric("Contacted (SMS or email)", contacted)
m6.metric("Qualified, not contacted", qualified_uncontacted)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Applies by day")
    daily = (
        df.groupby("apply_date", as_index=False)
        .size()
        .rename(columns={"size": "Applicants"})
        .sort_values("apply_date")
    )
    daily["apply_date"] = daily["apply_date"].astype(str)
    st.line_chart(daily.set_index("apply_date"), height=320)
    st.caption("Applicant count by date added to the pipeline (Central Time).")

with right:
    st.subheader("Applies by source")
    source_trend = (
        df.groupby(["apply_date", "source"], as_index=False)
        .size()
        .rename(columns={"size": "Applicants"})
        .sort_values(["apply_date", "source"])
    )
    source_trend["apply_date"] = source_trend["apply_date"].astype(str)
    source_pivot = source_trend.pivot(
        index="apply_date", columns="source", values="Applicants"
    ).fillna(0)
    st.line_chart(source_pivot, height=320)
    st.caption("Daily applicants by source (Central Time).")

st.subheader("Pipeline mix")
stage_counts = (
    df["pipeline_stage"]
    .map(lambda s: stage_labels.get(s, s))
    .value_counts()
    .rename_axis("Stage")
    .reset_index(name="Count")
    .sort_values("Stage")
)
st.line_chart(stage_counts.set_index("Stage"), height=260)
