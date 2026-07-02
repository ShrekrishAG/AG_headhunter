"""Phone screen scoring — Regional Manager & HR."""

from __future__ import annotations

from datetime import date

import streamlit as st

from lib.constants import (
    DIMENSIONS,
    GATES,
    INTERVIEWERS,
    PIPELINE_STAGES,
    SCORE_LABELS,
    SOURCES,
    VOTES,
    get_selected_role_slug,
    interviewer_keys,
)
from lib.scoring import (
    combined_r1_decision,
    compute_weighted_score,
    gates_passed,
    recommendation_label,
)
from lib.candidate_activity import log_r1_evaluation_saved, update_pipeline_stage
from lib.supabase_client import get_supabase


def _candidate_label(c: dict) -> str:
    parts = [c["full_name"]]
    if c.get("current_title"):
        parts.append(c["current_title"])
    if c.get("current_company"):
        parts.append(f"@ {c['current_company']}")
    return " · ".join(parts)


def _vote_index(existing_row: dict | None) -> int:
    if not existing_row or not existing_row.get("vote"):
        return 0
    votes = list(VOTES.keys())
    return votes.index(existing_row["vote"])


def _show_panel_summary(sb, candidate_id: str) -> None:
    gate_cols = ", ".join(key for key, _ in GATES)
    evals = (
        sb.table("r1_evaluations")
        .select(f"interviewer, weighted_score, vote, {gate_cols}")
        .eq("candidate_id", candidate_id)
        .execute()
        .data
    )
    if not evals:
        return

    st.divider()
    st.subheader("Panel summary")
    cols = st.columns(len(evals))
    for col, row in zip(cols, evals):
        with col:
            st.markdown(f"**{INTERVIEWERS[row['interviewer']]}**")
            st.write(f"Score: **{row.get('weighted_score') or '—'}** / 4.0")
            st.write(f"Vote: **{VOTES.get(row.get('vote'), '—')}**")

    keys = interviewer_keys()
    votes = {r["interviewer"]: r.get("vote") for r in evals}
    st.info(combined_r1_decision(*[votes.get(k) for k in keys[:2]]))


st.title("Phone screen · Qualification")
st.caption("30-min scorecard · Regional Manager & HR · save independently during or after the call")

sb = get_supabase()

roles = sb.table("roles").select("id, slug, title").execute().data
if not roles:
    st.error("No roles found. Run the Supabase migration first.")
    st.stop()

role_by_slug = {r["slug"]: r for r in roles}
default_role = role_by_slug.get(get_selected_role_slug(), roles[0])

with st.sidebar:
    interviewer = st.selectbox(
        "Interviewer",
        options=list(INTERVIEWERS.keys()),
        format_func=lambda k: INTERVIEWERS[k],
    )
    interview_date = st.date_input("Interview date", value=date.today())

tab_score, tab_add = st.tabs(["Score candidate", "Add candidate"])

with tab_add:
    st.subheader("Add candidate")
    with st.form("add_candidate", clear_on_submit=True):
        full_name = st.text_input("Full name *")
        c1, c2 = st.columns(2)
        with c1:
            current_title = st.text_input("Current title")
            source = st.selectbox("Source", SOURCES)
        with c2:
            current_company = st.text_input("Current company")
            stage = st.selectbox(
                "Pipeline stage",
                options=[s[0] for s in PIPELINE_STAGES],
                format_func=lambda k: dict(PIPELINE_STAGES)[k],
                index=3,  # round_1_scheduled default for live interviews
            )
        personal_network_contact = st.text_input(
            "Personal network contact",
            placeholder="e.g. Steve Mott — Dustin connection",
            help="Optional — who referred this candidate?",
        )
        phone = st.text_input("Mobile phone", placeholder="+19135551234")
        linkedin_url = st.text_input("LinkedIn URL")
        email = st.text_input("Email")
        notes = st.text_area("Notes")
        if st.form_submit_button("Create candidate", type="primary"):
            if not full_name.strip():
                st.error("Full name is required.")
            else:
                from lib.phone_utils import normalize_phone_us

                normalized_phone = normalize_phone_us(phone) if phone.strip() else None
                if phone.strip() and not normalized_phone:
                    st.error("Invalid phone number.")
                else:
                    sb.table("candidates").insert(
                        {
                            "role_id": default_role["id"],
                            "full_name": full_name.strip(),
                            "email": email or None,
                            "linkedin_url": linkedin_url or None,
                            "current_title": current_title or None,
                            "current_company": current_company or None,
                            "source": source,
                            "pipeline_stage": stage,
                            "notes": notes or None,
                            "personal_network_contact": personal_network_contact.strip() or None,
                            "phone": normalized_phone,
                        }
                    ).execute()
                    st.success(f"Added {full_name}")
                    st.rerun()

with tab_score:
    candidates = (
        sb.table("candidates")
        .select("id, full_name, current_title, current_company, pipeline_stage, linkedin_url")
        .eq("role_id", default_role["id"])
        .order("full_name")
        .execute()
        .data
    )

    if not candidates:
        st.info("No candidates yet. Add one in the **Add candidate** tab.")
        st.stop()

    candidate_options = {c["id"]: c for c in candidates}
    selected_id = st.selectbox(
        "Candidate",
        options=list(candidate_options.keys()),
        format_func=lambda cid: _candidate_label(candidate_options[cid]),
    )
    candidate = candidate_options[selected_id]

    existing_resp = (
        sb.table("r1_evaluations")
        .select("*")
        .eq("candidate_id", selected_id)
        .eq("interviewer", interviewer)
        .execute()
    )
    existing_row = existing_resp.data[0] if existing_resp.data else None

    if candidate.get("linkedin_url"):
        st.link_button("LinkedIn profile", candidate["linkedin_url"])

    st.markdown(f"**Stage:** `{candidate['pipeline_stage']}`")

    with st.form("r1_scorecard"):
        st.subheader(f"{INTERVIEWERS[interviewer]} · scorecard")

        scores: dict[str, int] = {}
        evidence: dict[str, str] = {}
        for dim in DIMENSIONS:
            st.markdown(f"**{dim['label']}** ({int(dim['weight'] * 100)}%)")
            st.caption(dim["hint"])
            c1, c2 = st.columns([1, 3])
            with c1:
                default_score = (
                    existing_row.get(dim["score_key"]) if existing_row else 3
                )
                scores[dim["score_key"]] = st.selectbox(
                    "Score",
                    options=[1, 2, 3, 4],
                    index=(default_score or 3) - 1,
                    format_func=lambda v: SCORE_LABELS[v],
                    key=dim["score_key"],
                    label_visibility="collapsed",
                )
            with c2:
                evidence[dim["evidence_key"]] = st.text_area(
                    "Evidence",
                    value=(existing_row or {}).get(dim["evidence_key"]) or "",
                    height=68,
                    key=dim["evidence_key"],
                    label_visibility="collapsed",
                    placeholder="Brief evidence from the call…",
                )

        st.divider()
        st.markdown("**Must-have gates**")
        gates: dict[str, bool] = {}
        gcols = st.columns(2)
        for i, (key, label) in enumerate(GATES):
            with gcols[i % 2]:
                gates[key] = st.checkbox(
                    label,
                    value=bool((existing_row or {}).get(key, False)),
                    key=key,
                )

        weighted = compute_weighted_score(scores)
        gates_ok = gates_passed(gates)
        rec = recommendation_label(weighted, gates_ok)

        m1, m2, m3 = st.columns(3)
        m1.metric("Weighted score", f"{weighted:.2f}" if weighted else "—")
        m2.metric("Gates", "Pass" if gates_ok else "Fail")
        m3.metric("Scorecard", rec)

        st.divider()
        vote = st.radio(
            "Vote",
            options=list(VOTES.keys()),
            format_func=lambda k: VOTES[k],
            horizontal=True,
            index=_vote_index(existing_row),
        )
        debrief_notes = st.text_area(
            "Debrief notes",
            value=(existing_row or {}).get("debrief_notes") or "",
            placeholder="Strengths, risks, open questions…",
        )

        submitted = st.form_submit_button(
            "Save scorecard" if not existing_row else "Update scorecard",
            type="primary",
        )

    if submitted:
        payload = {
            "candidate_id": selected_id,
            "interviewer": interviewer,
            "interview_date": interview_date.isoformat(),
            **scores,
            **evidence,
            **gates,
            "vote": vote,
            "debrief_notes": debrief_notes or None,
        }
        sb.table("r1_evaluations").upsert(
            payload,
            on_conflict="candidate_id,interviewer",
        ).execute()

        weighted = compute_weighted_score(scores)
        log_r1_evaluation_saved(
            sb,
            selected_id,
            interviewer=interviewer,
            vote=vote,
            weighted_score=weighted,
        )

        if candidate["pipeline_stage"] in (
            "identified",
            "qualified",
            "outreached",
            "round_1_scheduled",
        ):
            update_pipeline_stage(
                sb,
                selected_id,
                "round_1_complete",
                from_stage=candidate["pipeline_stage"],
                reason="r1_scorecard",
            )

        st.success("Scorecard saved.")
        st.rerun()

    _show_panel_summary(sb, selected_id)
