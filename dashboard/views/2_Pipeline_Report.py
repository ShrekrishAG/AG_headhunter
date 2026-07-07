"""Pipeline report — all candidates by round."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from lib.agent_prescreen import (
    format_agent_rank,
    format_score_badge,
    format_recommendation_label,
    load_agent_score_rationale,
    parse_agent_recommendation,
    parse_agent_score,
    rank_in_group,
    sort_by_agent_score,
)
from lib.candidate_display import (
    candidate_avatar_url,
    candidate_name_markdown,
    has_personal_network,
    link_button_new_tab,
    personal_network_contact,
)
from lib.export_display import format_exported_display
from lib.candidate_activity import (
    apply_outreach_stage,
    format_activity_line,
    format_outreach_summary,
    is_contacted,
    latest_outreach_draft,
    load_activities_by_candidate,
    log_email_sent,
    log_outreach_failed,
    log_sms_sent,
    tracking_available,
    update_pipeline_stage,
)
from lib.constants import (
    GATES,
    INTERVIEWERS,
    PIPELINE_DISPLAY_ORDER,
    PIPELINE_STAGES,
    SOURCES,
    STAGE_ORDER,
    VOTES,
    get_selected_role_slug,
    interviewer_keys,
)
from lib.phone_utils import normalize_phone_us
from lib.email_utils import normalize_email
from lib.llm_client import llm_configured, redraft_available, use_template_redraft
from lib.r1_draft_llm import redraft_r1_email, redraft_r1_sms
from lib.r1_email_invite import (
    DEFAULT_R1_EMAIL_BODY,
    DEFAULT_R1_EMAIL_SUBJECT,
    build_r1_email_body,
    build_r1_email_subject,
    send_r1_email,
    sendgrid_configured,
)
from lib.r1_invite import (
    DEFAULT_R1_SMS_TEMPLATE,
    MESSAGE_PLACEHOLDERS,
    build_r1_sms_body,
    calendly_configured,
    format_message_template,
    get_calendly_r1_url,
    send_r1_sms,
)
from lib.communications_status import outbound_sends_enabled, sms_ready
from lib.scoring import combined_r1_decision, format_vote, recommendation_label
from lib.supabase_client import get_supabase

BULK_SELECTED_KEY = "pipeline_bulk_selected"
BULK_SMS_TEMPLATE_KEY = "bulk_sms_template"
BULK_EMAIL_SUBJECT_KEY = "bulk_email_subject"
BULK_EMAIL_BODY_KEY = "bulk_email_body"
PIPELINE_METRIC_FILTER_KEY = "pipeline_metric_filter"
BULK_TEMPLATE_VERSION_KEY = "bulk_template_version"
# Bump when default SMS/email copy changes so the bulk editor picks up new templates.
CURRENT_BULK_TEMPLATE_VERSION = "2026-07-07-accord-defaults"

SAMPLE_PREVIEW_CANDIDATE = {
    "full_name": "Sample cand",
    "market": "TGC - KC, MO",
}


def _vote(cid: str, interviewer: str, evals_by_candidate: dict) -> str | None:
    for row in evals_by_candidate.get(cid, []):
        if row["interviewer"] == interviewer:
            return row.get("vote")
    return None


PIPELINE_METRICS: list[dict] = [
    {
        "id": "total",
        "label": "Total candidates",
        "help": "Everyone in the pipeline for this role, all stages.",
    },
    {
        "id": "qualified",
        "label": "Agent qualified",
        "help": "Resume pre-screen met the bar (65+). Stage: Resume qualified.",
    },
    {
        "id": "identified",
        "label": "Agent pass",
        "help": "Below threshold or not scored yet. Stage: Awaiting / below threshold.",
    },
    {
        "id": "network",
        "label": "Personal network ★",
        "help": "Referred via personal network (★ on their card).",
    },
    {
        "id": "outreached",
        "label": "Outreached",
        "help": "Invite sent (SMS/email). Waiting for them to book or reply. Stage: Outreached.",
    },
    {
        "id": "round_1_scheduled",
        "label": "R1 scheduled",
        "help": "Recruiter confirmed a phone screen is booked. Stage: Phone screen scheduled.",
    },
    {
        "id": "round_1_complete",
        "label": "R1 complete",
        "help": "Phone screen finished. Stage: Phone screen complete.",
    },
    {
        "id": "unanimous_advance",
        "label": "Unanimous R1 advance",
        "help": "Both R1 interviewers voted Advance on their scorecards.",
    },
    {
        "id": "contacted",
        "label": "Contacted",
        "help": "At least one SMS or email outreach was sent (any stage).",
    },
    {
        "id": "not_contacted",
        "label": "Not contacted",
        "help": "No SMS or email sent yet.",
    },
]


def _pipeline_metric_counts(candidates: list[dict], evals_by_candidate: dict) -> dict[str, int]:
    keys = interviewer_keys()[:2]
    unanimous = sum(
        1
        for c in candidates
        if combined_r1_decision(
            *[_vote(c["id"], k, evals_by_candidate) for k in keys]
        ).startswith("Unanimous")
    )
    return {
        "total": len(candidates),
        "qualified": sum(1 for c in candidates if c["pipeline_stage"] == "qualified"),
        "identified": sum(1 for c in candidates if c["pipeline_stage"] == "identified"),
        "network": sum(1 for c in candidates if has_personal_network(c)),
        "outreached": sum(1 for c in candidates if c["pipeline_stage"] == "outreached"),
        "round_1_scheduled": sum(1 for c in candidates if c["pipeline_stage"] == "round_1_scheduled"),
        "round_1_complete": sum(1 for c in candidates if c["pipeline_stage"] == "round_1_complete"),
        "unanimous_advance": unanimous,
        "contacted": sum(1 for c in candidates if is_contacted(c)),
        "not_contacted": sum(1 for c in candidates if not is_contacted(c)),
    }


def _filter_by_metric(
    candidates: list[dict],
    metric_id: str | None,
    evals_by_candidate: dict,
) -> list[dict]:
    if not metric_id or metric_id == "total":
        return candidates
    if metric_id == "qualified":
        return [c for c in candidates if c["pipeline_stage"] == "qualified"]
    if metric_id == "identified":
        return [c for c in candidates if c["pipeline_stage"] == "identified"]
    if metric_id == "network":
        return [c for c in candidates if has_personal_network(c)]
    if metric_id == "outreached":
        return [c for c in candidates if c["pipeline_stage"] == "outreached"]
    if metric_id == "round_1_scheduled":
        return [c for c in candidates if c["pipeline_stage"] == "round_1_scheduled"]
    if metric_id == "round_1_complete":
        return [c for c in candidates if c["pipeline_stage"] == "round_1_complete"]
    if metric_id == "unanimous_advance":
        keys = interviewer_keys()[:2]
        return [
            c
            for c in candidates
            if combined_r1_decision(
                *[_vote(c["id"], k, evals_by_candidate) for k in keys]
            ).startswith("Unanimous")
        ]
    if metric_id == "contacted":
        return [c for c in candidates if is_contacted(c)]
    if metric_id == "not_contacted":
        return [c for c in candidates if not is_contacted(c)]
    return candidates


def _render_clickable_metrics(
    counts: dict[str, int],
    active_metric: str | None,
) -> None:
    row1 = PIPELINE_METRICS[:4]
    row2 = PIPELINE_METRICS[4:8]
    row3 = PIPELINE_METRICS[8:]

    for row in (row1, row2, row3):
        cols = st.columns(len(row))
        for col, spec in zip(cols, row):
            metric_id = spec["id"]
            with col:
                if st.button(
                    str(counts.get(metric_id, 0)),
                    key=f"pipeline_metric_{metric_id}",
                    help=spec["help"],
                    use_container_width=True,
                    type="primary" if active_metric == metric_id else "secondary",
                ):
                    st.session_state[PIPELINE_METRIC_FILTER_KEY] = metric_id
                    st.rerun()
                st.caption(spec["label"])


def _reset_bulk_templates(*, rerun: bool = False) -> None:
    st.session_state[BULK_SMS_TEMPLATE_KEY] = DEFAULT_R1_SMS_TEMPLATE
    st.session_state[BULK_EMAIL_SUBJECT_KEY] = DEFAULT_R1_EMAIL_SUBJECT
    st.session_state[BULK_EMAIL_BODY_KEY] = DEFAULT_R1_EMAIL_BODY
    st.session_state[BULK_TEMPLATE_VERSION_KEY] = CURRENT_BULK_TEMPLATE_VERSION
    if rerun:
        st.rerun()


def _init_bulk_message_templates() -> None:
    if st.session_state.get(BULK_TEMPLATE_VERSION_KEY) != CURRENT_BULK_TEMPLATE_VERSION:
        for key in (
            BULK_SMS_TEMPLATE_KEY,
            BULK_EMAIL_SUBJECT_KEY,
            BULK_EMAIL_BODY_KEY,
            BULK_TEMPLATE_VERSION_KEY,
        ):
            st.session_state.pop(key, None)
        _reset_bulk_templates(rerun=True)
        return
    if BULK_SMS_TEMPLATE_KEY not in st.session_state:
        st.session_state[BULK_SMS_TEMPLATE_KEY] = DEFAULT_R1_SMS_TEMPLATE
    if BULK_EMAIL_SUBJECT_KEY not in st.session_state:
        st.session_state[BULK_EMAIL_SUBJECT_KEY] = DEFAULT_R1_EMAIL_SUBJECT
    if BULK_EMAIL_BODY_KEY not in st.session_state:
        st.session_state[BULK_EMAIL_BODY_KEY] = DEFAULT_R1_EMAIL_BODY
    if not (st.session_state.get(BULK_SMS_TEMPLATE_KEY) or "").strip():
        st.session_state[BULK_SMS_TEMPLATE_KEY] = DEFAULT_R1_SMS_TEMPLATE
    if not (st.session_state.get(BULK_EMAIL_SUBJECT_KEY) or "").strip():
        st.session_state[BULK_EMAIL_SUBJECT_KEY] = DEFAULT_R1_EMAIL_SUBJECT
    if not (st.session_state.get(BULK_EMAIL_BODY_KEY) or "").strip():
        st.session_state[BULK_EMAIL_BODY_KEY] = DEFAULT_R1_EMAIL_BODY


def _placeholder_caption() -> str:
    return "Placeholders: " + ", ".join(MESSAGE_PLACEHOLDERS)


def _personalize_preview(candidate: dict, template: str, calendly_url: str) -> str:
    try:
        return format_message_template(
            template,
            full_name=candidate["full_name"],
            calendly_url=calendly_url,
            market=candidate.get("market"),
        )
    except (KeyError, ValueError) as exc:
        return f"(Template error: {exc})"


def _bulk_send_sms(selected_candidates: list[dict], template: str, calendly_url: str) -> tuple[int, list[str]]:
    sent = 0
    errors: list[str] = []
    sb = get_supabase()
    for candidate in selected_candidates:
        phone = normalize_phone_us(candidate.get("phone") or "")
        if not phone:
            errors.append(f"{candidate['full_name']}: missing phone")
            log_outreach_failed(
                sb,
                candidate["id"],
                channel="sms",
                error="missing phone",
                bulk=True,
            )
            continue
        try:
            body = format_message_template(
                template,
                full_name=candidate["full_name"],
                calendly_url=calendly_url,
                market=candidate.get("market"),
            )
            sid = send_r1_sms(to_phone=phone, body=body)
            log_sms_sent(
                sb,
                candidate["id"],
                to_phone=phone,
                body=body,
                external_id=sid,
                bulk=True,
                phone=phone,
            )
            apply_outreach_stage(
                sb,
                candidate["id"],
                candidate.get("pipeline_stage") or "qualified",
                reason="bulk_sms_invite",
            )
            sent += 1
        except Exception as exc:
            errors.append(f"{candidate['full_name']}: {exc}")
            log_outreach_failed(
                sb,
                candidate["id"],
                channel="sms",
                error=str(exc),
                bulk=True,
            )
    return sent, errors


def _bulk_send_email(
    selected_candidates: list[dict],
    subject_template: str,
    body_template: str,
    calendly_url: str,
) -> tuple[int, list[str]]:
    sent = 0
    errors: list[str] = []
    sb = get_supabase()
    for candidate in selected_candidates:
        email = normalize_email(candidate.get("email") or "")
        if not email:
            errors.append(f"{candidate['full_name']}: missing email")
            log_outreach_failed(
                sb,
                candidate["id"],
                channel="email",
                error="missing email",
                bulk=True,
            )
            continue
        try:
            subject = build_r1_email_subject(
                subject_template,
                full_name=candidate["full_name"],
                calendly_url=calendly_url,
                market=candidate.get("market"),
            )
            body = format_message_template(
                body_template,
                full_name=candidate["full_name"],
                calendly_url=calendly_url,
                market=candidate.get("market"),
            )
            msg_id = send_r1_email(to_email=email, subject=subject, body=body)
            log_email_sent(
                sb,
                candidate["id"],
                to_email=email,
                subject=subject,
                body=body,
                external_id=msg_id,
                bulk=True,
                email=email,
            )
            apply_outreach_stage(
                sb,
                candidate["id"],
                candidate.get("pipeline_stage") or "qualified",
                reason="bulk_email_invite",
            )
            sent += 1
        except Exception as exc:
            errors.append(f"{candidate['full_name']}: {exc}")
            log_outreach_failed(
                sb,
                candidate["id"],
                channel="email",
                error=str(exc),
                bulk=True,
            )
    return sent, errors


def _bulk_selected() -> set[str]:
    if BULK_SELECTED_KEY not in st.session_state:
        st.session_state[BULK_SELECTED_KEY] = set()
    return st.session_state[BULK_SELECTED_KEY]


def _bulk_checkbox_key(candidate_id: str) -> str:
    return f"pipeline_bulk_cb_{candidate_id}"


def _sync_bulk_checkbox(candidate_id: str) -> None:
    selected = _bulk_selected()
    if st.session_state.get(_bulk_checkbox_key(candidate_id)):
        selected.add(candidate_id)
    else:
        selected.discard(candidate_id)


def _render_bulk_checkbox(candidate_id: str) -> None:
    key = _bulk_checkbox_key(candidate_id)
    if key not in st.session_state:
        st.session_state[key] = candidate_id in _bulk_selected()
    st.checkbox(
        "Select",
        key=key,
        on_change=_sync_bulk_checkbox,
        args=(candidate_id,),
        label_visibility="collapsed",
    )


def _select_all_visible(candidate_ids: list[str]) -> None:
    selected = _bulk_selected()
    for candidate_id in candidate_ids:
        selected.add(candidate_id)
        st.session_state[_bulk_checkbox_key(candidate_id)] = True


def _clear_bulk_selection(candidate_ids: list[str] | None = None) -> None:
    selected = _bulk_selected()
    ids_to_clear = list(selected) if candidate_ids is None else candidate_ids
    for candidate_id in ids_to_clear:
        selected.discard(candidate_id)
        st.session_state[_bulk_checkbox_key(candidate_id)] = False


def _sync_table_selection(candidates: list[dict], selected_flags: list[bool]) -> None:
    selected = _bulk_selected()
    visible_ids = {c["id"] for c in candidates}
    selected -= visible_ids
    for candidate, is_selected in zip(candidates, selected_flags):
        if is_selected:
            selected.add(candidate["id"])
            st.session_state[_bulk_checkbox_key(candidate["id"])] = True
        else:
            st.session_state[_bulk_checkbox_key(candidate["id"])] = False


def _render_bulk_action_bar(visible_candidates: list[dict], stage_labels: dict) -> None:
    _init_bulk_message_templates()
    visible_ids = [c["id"] for c in visible_candidates]
    selected = _bulk_selected()
    selected_in_view = selected.intersection(visible_ids)
    selected_candidates = [c for c in visible_candidates if c["id"] in selected_in_view]
    calendly_url = get_calendly_r1_url() or "https://calendly.com/your-link"
    placeholder_help = _placeholder_caption()

    with st.container(border=True):
        st.markdown("**Bulk actions**")
        col_select, col_clear, col_count, col_stage, col_apply = st.columns([1.1, 1, 1.2, 2.2, 1.2])
        with col_select:
            if st.button("Select all", key="bulk_select_all", use_container_width=True):
                _select_all_visible(visible_ids)
                st.rerun()
        with col_clear:
            if st.button("Clear", key="bulk_clear", use_container_width=True):
                _clear_bulk_selection(visible_ids)
                st.rerun()
        with col_count:
            st.metric("Selected", len(selected_in_view))

        stage_options = STAGE_ORDER
        with col_stage:
            target_stage = st.selectbox(
                "Move to stage",
                options=stage_options,
                format_func=lambda key: stage_labels.get(key, key),
                key="bulk_target_stage",
            )
        with col_apply:
            st.write("")
            if st.button(
                "Apply to selected",
                key="bulk_apply_stage",
                type="primary",
                disabled=not selected_in_view,
                use_container_width=True,
            ):
                sb = get_supabase()
                by_id = {c["id"]: c for c in visible_candidates}
                for candidate_id in selected_in_view:
                    candidate = by_id.get(candidate_id, {})
                    update_pipeline_stage(
                        sb,
                        candidate_id,
                        target_stage,
                        from_stage=candidate.get("pipeline_stage"),
                        reason="bulk_stage_action",
                    )
                st.success(
                    f"Moved {len(selected_in_view)} candidate(s) to "
                    f"{stage_labels.get(target_stage, target_stage)}."
                )
                _clear_bulk_selection(list(selected_in_view))
                st.rerun()

        st.divider()
        st.markdown("**Bulk messages**")
        msg_hdr, msg_reset = st.columns([4, 1])
        with msg_hdr:
            st.caption(placeholder_help)
        with msg_reset:
            if st.button("Reset templates", key="bulk_reset_templates", use_container_width=True):
                for key in (
                    BULK_SMS_TEMPLATE_KEY,
                    BULK_EMAIL_SUBJECT_KEY,
                    BULK_EMAIL_BODY_KEY,
                ):
                    st.session_state.pop(key, None)
                _reset_bulk_templates(rerun=True)

        preview_candidate = (
            selected_candidates[0] if selected_candidates else SAMPLE_PREVIEW_CANDIDATE
        )
        preview_label = (
            preview_candidate["full_name"]
            if selected_candidates
            else f"{preview_candidate['full_name']} (example — select candidates to preview real names/markets)"
        )

        sms_tab, email_tab = st.tabs(["SMS", "Email"])
        with sms_tab:
            st.text_area(
                "SMS template",
                key=BULK_SMS_TEMPLATE_KEY,
                height=140,
                help=placeholder_help,
            )
            st.caption(f"Preview for **{preview_label}**:")
            st.text(
                _personalize_preview(
                    preview_candidate,
                    st.session_state[BULK_SMS_TEMPLATE_KEY],
                    calendly_url,
                )
            )
            if selected_candidates and len(selected_candidates) > 1:
                with st.expander(f"Preview all {len(selected_candidates)} selected"):
                    for candidate in selected_candidates:
                        st.markdown(f"**{candidate['full_name']}**")
                        st.text(
                            _personalize_preview(
                                candidate,
                                st.session_state[BULK_SMS_TEMPLATE_KEY],
                                calendly_url,
                            )
                        )
                        st.divider()

            if not outbound_sends_enabled():
                st.info("Bulk SMS send is disabled (`OUTBOUND_SENDS_ENABLED=false`). Draft and preview only.")
            elif not sms_ready():
                st.warning("Configure Heymarket (or Twilio) and Calendly before sending bulk SMS.")

            if st.button(
                "Send SMS to selected",
                key="bulk_send_sms",
                type="primary",
                disabled=not (
                    selected_in_view
                    and sms_ready()
                ),
            ):
                sent, errors = _bulk_send_sms(
                    selected_candidates,
                    st.session_state[BULK_SMS_TEMPLATE_KEY].strip(),
                    calendly_url,
                )
                if sent:
                    st.success(f"Sent SMS to {sent} candidate(s).")
                for err in errors:
                    st.warning(err)
                if sent:
                    st.rerun()

        with email_tab:
            st.text_input(
                "Email subject",
                key=BULK_EMAIL_SUBJECT_KEY,
                help=placeholder_help,
            )
            st.text_area(
                "Email body",
                key=BULK_EMAIL_BODY_KEY,
                height=320,
                help=placeholder_help,
            )
            st.caption(f"Preview for **{preview_label}**:")
            st.markdown(
                f"**Subject:** {_personalize_preview(preview_candidate, st.session_state[BULK_EMAIL_SUBJECT_KEY], calendly_url)}"
            )
            st.text(
                _personalize_preview(
                    preview_candidate,
                    st.session_state[BULK_EMAIL_BODY_KEY],
                    calendly_url,
                )
            )
            if selected_candidates and len(selected_candidates) > 1:
                with st.expander(f"Preview all {len(selected_candidates)} selected"):
                    for candidate in selected_candidates:
                        st.markdown(f"**{candidate['full_name']}**")
                        st.markdown(
                            f"Subject: {_personalize_preview(candidate, st.session_state[BULK_EMAIL_SUBJECT_KEY], calendly_url)}"
                        )
                        st.text(
                            _personalize_preview(
                                candidate,
                                st.session_state[BULK_EMAIL_BODY_KEY],
                                calendly_url,
                            )
                        )
                        st.divider()

            if not outbound_sends_enabled():
                st.info("Bulk email send is disabled (`OUTBOUND_SENDS_ENABLED=false`). Draft and preview only.")
            elif not sendgrid_configured() or not calendly_configured():
                st.warning("Configure SendGrid and Calendly before sending bulk email.")

            if st.button(
                "Send email to selected",
                key="bulk_send_email",
                type="primary",
                disabled=not (
                    selected_in_view
                    and outbound_sends_enabled()
                    and sendgrid_configured()
                    and calendly_configured()
                ),
            ):
                sent, errors = _bulk_send_email(
                    selected_candidates,
                    st.session_state[BULK_EMAIL_SUBJECT_KEY].strip(),
                    st.session_state[BULK_EMAIL_BODY_KEY].strip(),
                    calendly_url,
                )
                if sent:
                    st.success(f"Sent email to {sent} candidate(s).")
                for err in errors:
                    st.warning(err)
                if sent:
                    st.rerun()


def _sms_draft_key(candidate_id: str) -> str:
    return f"r1_sms_draft_{candidate_id}"


def _email_subject_key(candidate_id: str) -> str:
    return f"r1_email_subject_{candidate_id}"


def _email_body_key(candidate_id: str) -> str:
    return f"r1_email_draft_{candidate_id}"


def _run_pending_redraft(*, pending_key: str, error_key: str, spinner_label: str, run) -> None:
    if not st.session_state.pop(pending_key, False):
        return
    if not redraft_available():
        st.session_state[error_key] = (
            "Redraft unavailable. Set REDRAFT_MODE=template in dashboard/.env "
            "or add OPENAI_API_KEY for AI redrafts."
        )
        return
    try:
        with st.spinner(
            spinner_label if not use_template_redraft() else "Applying template variation…"
        ):
            run()
    except Exception as exc:
        st.session_state[error_key] = str(exc)


def _show_redraft_error(error_key: str) -> None:
    if error_key in st.session_state:
        st.error(f"Redraft failed: {st.session_state.pop(error_key)}")


def _redraft_button(*, label: str, pending_key: str, button_key: str) -> None:
    if st.button(label, key=button_key, use_container_width=True):
        st.session_state[pending_key] = True
        st.rerun()


def _display_name(c: dict) -> str:
    name = c["full_name"]
    return f"★ {name}" if has_personal_network(c) else name


def _render_table(candidates, evals_by_candidate, stage_labels, activities_by_candidate):
    if not candidates:
        st.info("No candidates to show in table.")
        return
    ranked_pool = sort_by_agent_score(candidates)
    ranks = rank_in_group(ranked_pool)
    selected = _bulk_selected()
    rows = []
    for c in ranked_pool:
        rec = parse_agent_recommendation(c)
        score = parse_agent_score(c)
        score_display = f"{score}/100" if score is not None else "—"
        rank_val = ranks.get(c["id"])
        rows.append(
            {
                "Select": bool(c["id"] in selected),
                "Rank": str(rank_val) if rank_val is not None else "—",
                "Name": _display_name(c),
                "Score": score_display,
                "Recommendation": rec or "Not scored",
                "Market": c.get("market") or "—",
                "Stage": stage_labels.get(c["pipeline_stage"], c["pipeline_stage"]),
                "Outreach": format_outreach_summary(c),
                "Exported": format_exported_display(
                    c, activities=activities_by_candidate.get(c["id"], [])
                ),
                "Source": c.get("source") or "—",
                "Phone": c.get("phone") or "—",
                "Email": c.get("email") or "—",
            }
        )
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", default=False, width="small"),
        },
        disabled=[column for column in df.columns if column != "Select"],
        hide_index=True,
        use_container_width=True,
        key=f"pipeline_table_editor_{len(candidates)}",
    )
    if "Select" in edited.columns:
        _sync_table_selection(ranked_pool, edited["Select"].astype(bool).tolist())


def _render_r1_invite(c: dict) -> None:
    calendly_url = get_calendly_r1_url()

    with st.expander("Send R1 invite (SMS)", expanded=False):
        if c.get("r1_invite_sent_at"):
            st.caption(f"Last sent: {c['r1_invite_sent_at']}")

        if not calendly_configured() and not calendly_url:
            st.warning("Add `CALENDLY_R1_URL` to `dashboard/.env` or Streamlit Secrets.")
        if not sms_ready() and not calendly_configured():
            st.info("SMS not configured yet — you can still draft and approve copy below.")
        elif not sms_ready():
            st.info("Configure Heymarket (or Twilio) to send SMS.")
        if not outbound_sends_enabled():
            st.warning("Send SMS is disabled — set `OUTBOUND_SENDS_ENABLED=true` in `.env` when ready to send.")

        default_body = build_r1_sms_body(
            c["full_name"],
            calendly_url or "https://calendly.com/your-link",
            market=c.get("market"),
        )
        draft_key = _sms_draft_key(c["id"])
        pending_key = f"{draft_key}_pending"
        error_key = f"{draft_key}_error"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = default_body

        cal_url = calendly_url or "https://calendly.com/your-link"

        def _run_sms_redraft() -> None:
            st.session_state[draft_key] = redraft_r1_sms(
                c,
                cal_url,
                previous_draft=st.session_state.get(draft_key),
            )

        _run_pending_redraft(
            pending_key=pending_key,
            error_key=error_key,
            spinner_label="Regenerating SMS draft…",
            run=_run_sms_redraft,
        )
        _show_redraft_error(error_key)

        redraft_col, _ = st.columns([1, 4])
        with redraft_col:
            _redraft_button(
                label="Redraft",
                pending_key=pending_key,
                button_key=f"sms_redraft_{c['id']}",
            )

        with st.form(key=f"r1_invite_{c['id']}"):
            phone_val = st.text_input(
                "Mobile phone",
                value=c.get("phone") or "",
                placeholder="+19135551234",
            )
            sms_body = st.text_area(
                "SMS message (edit before sending)",
                value=st.session_state[draft_key],
                height=220,
                help="Review and edit the message. Nothing sends until you click Send SMS.",
            )
            col_save, col_send = st.columns(2)
            save_only = col_save.form_submit_button("Save phone only")
            send_btn = col_send.form_submit_button(
                "Send SMS",
                type="primary",
                disabled=not (outbound_sends_enabled() and sms_ready() and calendly_url),
            )

            if save_only:
                normalized = normalize_phone_us(phone_val)
                if phone_val.strip() and not normalized:
                    st.error("Enter a valid 10-digit US mobile number.")
                else:
                    get_supabase().table("candidates").update(
                        {"phone": normalized or phone_val.strip() or None}
                    ).eq("id", c["id"]).execute()
                    st.success("Phone saved.")
                    st.rerun()

            if send_btn:
                if not outbound_sends_enabled():
                    st.error("Outbound sends are disabled — see Communications page.")
                elif not calendly_url:
                    st.error("CALENDLY_R1_URL is missing.")
                elif not sms_ready():
                    st.error("SMS credentials missing — see Communications page.")
                elif not sms_body.strip():
                    st.error("SMS message cannot be empty.")
                else:
                    normalized = normalize_phone_us(phone_val)
                    if not normalized:
                        st.error("Enter a valid mobile number before sending.")
                    else:
                        try:
                            sb = get_supabase()
                            sid = send_r1_sms(to_phone=normalized, body=sms_body.strip())
                            log_sms_sent(
                                sb,
                                c["id"],
                                to_phone=normalized,
                                body=sms_body.strip(),
                                external_id=sid,
                                phone=normalized,
                            )
                            moved = apply_outreach_stage(
                                sb,
                                c["id"],
                                c.get("pipeline_stage") or "qualified",
                                reason="sms_invite",
                            )
                            if moved:
                                st.success(
                                    f"SMS sent (SID {sid[:8]}…). Stage → Outreached."
                                )
                            else:
                                st.success(f"SMS sent (SID {sid[:8]}…).")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Send failed: {exc}")
                            log_outreach_failed(sb, c["id"], channel="sms", error=str(exc))


def _render_r1_email_invite(c: dict) -> None:
    calendly_url = get_calendly_r1_url()

    with st.expander("Send R1 invite (email)", expanded=False):
        if c.get("r1_invite_sent_at"):
            st.caption(f"Last invite sent: {c['r1_invite_sent_at']}")

        if not calendly_configured() and not calendly_url:
            st.warning("Add `CALENDLY_R1_URL` to `dashboard/.env` or Streamlit Secrets.")
        if not sendgrid_configured():
            st.info("SendGrid not configured yet — draft and approve copy below.")
        if not outbound_sends_enabled():
            st.warning("Send email is disabled — set `OUTBOUND_SENDS_ENABLED=true` in `.env` when ready to send.")

        default_subject = build_r1_email_subject(
            full_name=c["full_name"],
            calendly_url=calendly_url or "https://calendly.com/your-link",
            market=c.get("market"),
        )
        default_body = build_r1_email_body(
            c["full_name"],
            calendly_url or "https://calendly.com/your-link",
            market=c.get("market"),
        )
        subject_key = _email_subject_key(c["id"])
        body_key = _email_body_key(c["id"])
        pending_key = f"{body_key}_pending"
        error_key = f"{body_key}_error"
        if subject_key not in st.session_state:
            st.session_state[subject_key] = default_subject
        if body_key not in st.session_state:
            st.session_state[body_key] = default_body

        cal_url = calendly_url or "https://calendly.com/your-link"

        def _run_email_redraft() -> None:
            new_subject, new_body = redraft_r1_email(
                c,
                cal_url,
                previous_subject=st.session_state.get(subject_key),
                previous_body=st.session_state.get(body_key),
            )
            st.session_state[subject_key] = new_subject
            st.session_state[body_key] = new_body

        _run_pending_redraft(
            pending_key=pending_key,
            error_key=error_key,
            spinner_label="Regenerating email draft…",
            run=_run_email_redraft,
        )
        _show_redraft_error(error_key)

        redraft_col, _ = st.columns([1, 4])
        with redraft_col:
            _redraft_button(
                label="Redraft",
                pending_key=pending_key,
                button_key=f"email_redraft_{c['id']}",
            )

        with st.form(key=f"r1_email_{c['id']}"):
            email_val = st.text_input(
                "Email",
                value=c.get("email") or "",
                placeholder="candidate@example.com",
            )
            subject = st.text_input("Subject", value=st.session_state[subject_key])
            email_body = st.text_area(
                "Email message (edit before sending)",
                value=st.session_state[body_key],
                height=260,
                help="Review and edit. Nothing sends until you click Send email.",
            )
            col_save, col_send = st.columns(2)
            save_only = col_save.form_submit_button("Save email only")
            send_btn = col_send.form_submit_button(
                "Send email",
                type="primary",
                disabled=not (outbound_sends_enabled() and sendgrid_configured() and calendly_url),
            )

            if save_only:
                normalized = normalize_email(email_val) if email_val.strip() else None
                if email_val.strip() and not normalized:
                    st.error("Enter a valid email address.")
                else:
                    get_supabase().table("candidates").update(
                        {"email": normalized or email_val.strip() or None}
                    ).eq("id", c["id"]).execute()
                    st.success("Email saved.")
                    st.rerun()

            if send_btn:
                if not outbound_sends_enabled():
                    st.error("Outbound sends are disabled — see Communications page.")
                elif not calendly_url:
                    st.error("CALENDLY_R1_URL is missing.")
                elif not sendgrid_configured():
                    st.error("SendGrid credentials missing — see Communications page.")
                elif not subject.strip() or not email_body.strip():
                    st.error("Subject and message cannot be empty.")
                else:
                    normalized = normalize_email(email_val)
                    if not normalized:
                        st.error("Enter a valid email address before sending.")
                    else:
                        try:
                            sb = get_supabase()
                            msg_id = send_r1_email(
                                to_email=normalized,
                                subject=subject.strip(),
                                body=email_body.strip(),
                            )
                            log_email_sent(
                                sb,
                                c["id"],
                                to_email=normalized,
                                subject=subject.strip(),
                                body=email_body.strip(),
                                external_id=msg_id,
                                email=normalized,
                            )
                            moved = apply_outreach_stage(
                                sb,
                                c["id"],
                                c.get("pipeline_stage") or "qualified",
                                reason="email_invite",
                            )
                            if moved:
                                st.success(
                                    f"Email queued (id {msg_id[:12]}…). Stage → Outreached."
                                )
                            else:
                                st.success(f"Email queued (id {msg_id[:12]}…).")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Send failed: {exc}")
                            log_outreach_failed(sb, c["id"], channel="email", error=str(exc))


def _render_activity_timeline(activities: list[dict], stage_labels: dict) -> None:
    if not activities:
        return
    with st.expander("Activity timeline", expanded=False):
        for activity in activities:
            st.markdown(format_activity_line(activity, stage_labels))


def _render_suggested_draft_reference(activities: list[dict]) -> None:
    draft_activity = latest_outreach_draft(activities)
    if not draft_activity:
        return
    payload = draft_activity.get("payload") or {}
    with st.expander("Suggested outreach (reference only)", expanded=False):
        st.caption(
            "AI-generated draft for context — the Send SMS / Send email boxes below "
            "use the default template, not this text."
        )
        st.markdown("**SMS reference**")
        st.text(payload.get("sms_body") or "—")
        st.markdown(f"**Email subject:** {payload.get('email_subject') or '—'}")
        st.markdown("**Email body reference**")
        st.text(payload.get("email_body") or "—")


def _render_candidate_card(
    c,
    evals_by_candidate,
    stage_labels,
    agent_rank: int | None,
    activities: list[dict] | None = None,
):
    select_col, card_col = st.columns([0.06, 1])
    with select_col:
        st.write("")
        _render_bulk_checkbox(c["id"])
    with card_col:
        _render_candidate_card_body(
            c,
            evals_by_candidate,
            stage_labels,
            agent_rank,
            activities or [],
        )


def _render_candidate_card_body(
    c,
    evals_by_candidate,
    stage_labels,
    agent_rank: int | None,
    activities: list[dict],
):
    score_col, info_col, actions_col = st.columns([1.2, 3.8, 2])
    with score_col:
        score = parse_agent_score(c)
        rec = parse_agent_recommendation(c)
        if score is not None:
            st.metric("Resume score", f"{score}/100")
            st.caption(format_recommendation_label(rec))
        else:
            st.metric("Resume score", "—")
            st.caption("Not scored yet")
        if agent_rank is not None:
            st.caption(f"Rank #{agent_rank}")
    avatar_col, detail_col = info_col.columns([1, 5])
    with avatar_col:
        st.image(candidate_avatar_url(c), width=72)
    with detail_col:
        st.markdown(candidate_name_markdown(c))
        st.markdown(format_score_badge(c))
        if has_personal_network(c):
            st.markdown(f"**Personal network:** {personal_network_contact(c)}")
        sub = []
        if c.get("current_title"):
            sub.append(c["current_title"])
        if c.get("current_company"):
            sub.append(c["current_company"])
        if sub:
            st.caption(" · ".join(sub))
        if c.get("market"):
            st.write(f"**Market:** {c['market']}")
        rationale = load_agent_score_rationale(c)
        if rationale:
            st.markdown(rationale)
        st.write(f"**Source:** {c.get('source') or '—'}")
        exported_label = format_exported_display(c, activities=activities)
        if exported_label != "—":
            st.write(f"**Exported:** {exported_label}")
            if c.get("export_batch"):
                st.caption(f"Batch `{c['export_batch']}`")
        if c.get("email"):
            st.write(f"**Email:** {c['email']}")
        if c.get("phone"):
            st.write(f"**Phone:** {c['phone']}")
        st.write(f"**Stage:** {stage_labels.get(c['pipeline_stage'], c['pipeline_stage'])}")
        st.caption(f"**Outreach:** {format_outreach_summary(c)}")
    with actions_col:
        if c.get("linkedin_url"):
            link_button_new_tab("LinkedIn", c["linkedin_url"])
        if c.get("resume_url"):
            link_button_new_tab("Resume", c["resume_url"])

    ev = evals_by_candidate.get(c["id"], [])
    if ev:
        cols = st.columns(len(ev))
        for col, row in zip(cols, ev):
            with col:
                gates_ok = all(row.get(key) for key, _ in GATES)
                st.markdown(f"**{INTERVIEWERS[row['interviewer']]}**")
                st.write(f"Score: {row.get('weighted_score') or '—'}")
                st.write(f"Vote: {VOTES.get(row.get('vote'), '—')}")
                st.write(
                    f"Rec: {recommendation_label(row.get('weighted_score'), gates_ok)}"
                )
        votes = {r["interviewer"]: r.get("vote") for r in ev}
        st.success(combined_r1_decision(*[_vote(c["id"], k, evals_by_candidate) for k in interviewer_keys()[:2]]))
    else:
        st.caption("No R1 scorecards yet.")

    _render_activity_timeline(activities, stage_labels)
    _render_suggested_draft_reference(activities)

    with st.expander("Contact, source & stage", expanded=False):
        with st.form(key=f"contact_form_{c['id']}"):
            current_stage = c.get("pipeline_stage") or "identified"
            stage_index = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else 0
            new_stage = st.selectbox(
                "Pipeline stage",
                options=STAGE_ORDER,
                index=stage_index,
                format_func=lambda key: stage_labels.get(key, key),
                key=f"stage_{c['id']}",
                help="Manual update — e.g. Outreached → Phone screen scheduled when they book.",
            )
            new_source = st.selectbox(
                "Source",
                SOURCES,
                index=SOURCES.index(c["source"]) if c.get("source") in SOURCES else 0,
                key=f"source_{c['id']}",
            )
            new_net = st.text_input(
                "Personal network contact",
                value=personal_network_contact(c) or "",
                placeholder="e.g. Steve Mott — Dustin connection",
                help="Who referred this candidate? Independent of apply source.",
                key=f"net_{c['id']}",
            )
            new_phone = st.text_input(
                "Mobile phone",
                value=c.get("phone") or "",
                key=f"phone_{c['id']}",
            )
            if st.form_submit_button("Save"):
                normalized = normalize_phone_us(new_phone) if new_phone.strip() else None
                if new_phone.strip() and not normalized:
                    st.error("Invalid phone number.")
                else:
                    sb = get_supabase()
                    if new_stage != current_stage:
                        update_pipeline_stage(
                            sb,
                            c["id"],
                            new_stage,
                            from_stage=current_stage,
                            reason="manual_recruiter",
                        )
                    sb.table("candidates").update(
                        {
                            "source": new_source,
                            "personal_network_contact": new_net.strip() or None,
                            "phone": normalized,
                        }
                    ).eq("id", c["id"]).execute()
                    st.success("Saved.")
                    st.rerun()

    if c["pipeline_stage"] in ("qualified", "outreached", "round_1_scheduled", "round_1_complete"):
        _render_r1_invite(c)
        _render_r1_email_invite(c)

    st.divider()


st.title("Pipeline report")
st.caption(
    "Project Sales Rep resumes scored on 100-point rubric · "
    "85+ Strong interview · 70–84 Good candidate · 60–69 Phone screen · <60 Likely not a fit"
)

_init_bulk_message_templates()

sb = get_supabase()

roles = sb.table("roles").select("id, slug, title").execute().data
role = next((r for r in roles if r["slug"] == get_selected_role_slug()), roles[0])

candidates = (
    sb.table("candidates")
    .select("*")
    .eq("role_id", role["id"])
    .order("updated_at", desc=True)
    .execute()
    .data
)

evals = sb.table("r1_evaluations").select("*").execute().data
evals_by_candidate: dict[str, list] = {}
for row in evals:
    evals_by_candidate.setdefault(row["candidate_id"], []).append(row)

stage_labels = dict(PIPELINE_STAGES)

metric_counts = _pipeline_metric_counts(candidates, evals_by_candidate)
active_metric = st.session_state.get(PIPELINE_METRIC_FILTER_KEY)

_render_clickable_metrics(metric_counts, active_metric)

if active_metric and active_metric != "total":
    spec = next((m for m in PIPELINE_METRICS if m["id"] == active_metric), None)
    label = spec["label"] if spec else active_metric
    clear_col, _ = st.columns([1, 5])
    with clear_col:
        if st.button("Clear metric filter", key="pipeline_clear_metric"):
            st.session_state.pop(PIPELINE_METRIC_FILTER_KEY, None)
            st.rerun()
    st.markdown(f"Showing: **{label}** ({metric_counts.get(active_metric, 0)} in this group)")

st.divider()

filter_contact = st.radio(
    "Contact status",
    options=["All", "Contacted", "Not contacted"],
    horizontal=True,
    key="pipeline_filter_contact",
)

filter_stage = st.multiselect(
    "Filter stages",
    options=STAGE_ORDER,
    format_func=lambda k: stage_labels.get(k, k),
    default=[],
    key="pipeline_filter_stage",
)

filtered = _filter_by_metric(
    candidates,
    active_metric,
    evals_by_candidate,
)
if filter_contact == "Contacted":
    filtered = [c for c in filtered if is_contacted(c)]
elif filter_contact == "Not contacted":
    filtered = [c for c in filtered if not is_contacted(c)]
if filter_stage:
    filtered = [c for c in filtered if c["pipeline_stage"] in filter_stage]

if not filtered:
    st.info("No candidates match this filter.")
    st.stop()

activities_by_candidate = load_activities_by_candidate(sb, [c["id"] for c in filtered])
if not tracking_available(sb):
    st.caption("Activity tracking: run `scripts/apply-activity-tracking-migration.py` and apply SQL in Supabase.")

_render_bulk_action_bar(filtered, stage_labels)

view = st.radio("View", ["By stage", "Table"], horizontal=True)

if view == "Table":
    _render_table(filtered, evals_by_candidate, stage_labels, activities_by_candidate)
else:
    grouped: dict[str, list] = {s: [] for s in PIPELINE_DISPLAY_ORDER}
    for c in filtered:
        grouped.setdefault(c["pipeline_stage"], []).append(c)

    for stage in PIPELINE_DISPLAY_ORDER:
        group = grouped.get(stage, [])
        if not group:
            continue
        sorted_group = sort_by_agent_score(group)
        ranks = rank_in_group(sorted_group)
        with st.expander(
            f"{stage_labels.get(stage, stage)} ({len(sorted_group)})",
            expanded=stage in ("qualified", "outreached", "round_1_scheduled"),
        ):
            stage_ids = [c["id"] for c in sorted_group]
            if st.button(
                "Select all",
                key=f"stage_select_all_{stage}",
                use_container_width=False,
            ):
                _select_all_visible(stage_ids)
                st.rerun()
            for c in sorted_group:
                _render_candidate_card(
                    c,
                    evals_by_candidate,
                    stage_labels,
                    ranks.get(c["id"]),
                    activities_by_candidate.get(c["id"], []),
                )
