"""Manager packets — fair sales candidate distribution to market GMs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from lib.communications_status import outbound_sends_enabled
from lib.constants import APP_NAME, DASHBOARD_ROOT, get_selected_role_title
from lib.manager_markets import load_market_managers
from lib.manager_packets import (
    AssignmentPreview,
    EXPORTS_ROOT,
    REQUIRED_PACKET_COPY_EMAILS,
    build_assignment_preview,
    list_export_batches,
    load_recent_sends,
    preview_packet_email,
    send_all_packets,
    tracking_available,
    verify_copy_recipients_for_packets,
)
from lib.r1_email_invite import sendgrid_configured
from lib.supabase_client import get_supabase

st.title("Manager packets")
st.caption(
    f"{APP_NAME} · {get_selected_role_title()} · "
    "Fair-split export batches and email zip packets to market GMs"
)

sb = get_supabase()

if not tracking_available(sb):
    st.warning(
        "Send log table is missing. Apply "
        "`supabase/migrations/20260716120000_manager_packet_sends.sql` "
        "in the Supabase SQL editor before sending (needed for never-send-twice)."
    )

markets = load_market_managers()
with st.expander("Configured markets & GMs", expanded=False):
    rows = []
    for market in markets:
        rows.append(
            {
                "Project": market.project,
                "Market": market.market,
                "GMs": ", ".join(market.manager_emails),
                "Count": len(market.manager_emails),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Config: `{DASHBOARD_ROOT / 'config' / 'manager_markets.yaml'}`")

batches = list_export_batches()
if not batches:
    st.info(
        f"No ZipRecruiter exports found under `{EXPORTS_ROOT}`. "
        "Run a sales export from the Slack bot first."
    )
    st.stop()

batch_labels = {
    b["batch"]: f"{b['created_display']} · {b['candidate_count']} candidates · `{b['batch']}`"
    for b in batches
}
selected_batch = st.selectbox(
    "Recent export batch",
    options=[b["batch"] for b in batches],
    format_func=lambda key: batch_labels.get(key, key),
)
export_dir = Path(next(b["path"] for b in batches if b["batch"] == selected_batch))

col_preview, col_status = st.columns([1, 1])
with col_preview:
    build_preview = st.button("Preview assignment", type="primary", use_container_width=True)
with col_status:
    st.caption("Preview builds fair packets (snake-draft by score when available). Scores are not emailed.")

if build_preview or st.session_state.get("manager_packet_preview_batch") == selected_batch:
    preview: AssignmentPreview = build_assignment_preview(sb, export_dir)
    st.session_state["manager_packet_preview_batch"] = selected_batch
    st.session_state["manager_packet_preview"] = preview
else:
    preview = st.session_state.get("manager_packet_preview")
    if preview is None or preview.export_batch != selected_batch:
        preview = None

if preview is None:
    st.info("Click **Preview assignment** to see how this batch would be split.")
else:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("In export", preview.total_candidates)
    m2.metric("Packets", len(preview.packets))
    m3.metric("Already sent (excluded)", preview.excluded_already_sent)
    m4.metric("Other projects skipped", preview.skipped_unknown_project)

    if not preview.packets:
        st.warning(
            "No packets to send. All sales-market candidates may already be sent, "
            "or this batch has no configured market projects."
        )
    else:
        table_rows = []
        for packet in preview.packets:
            table_rows.append(
                {
                    "Market": packet.market,
                    "Project": packet.project_name,
                    "Manager": packet.manager_email,
                    "Candidates": len(packet.candidates),
                    "Names": ", ".join(c.name for c in packet.candidates[:8])
                    + ("…" if len(packet.candidates) > 8 else ""),
                }
            )
        st.subheader("Packet preview")
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        with st.expander("Candidate detail by packet", expanded=False):
            for packet in preview.packets:
                st.markdown(
                    f"**{packet.market}** → `{packet.manager_email}` "
                    f"({len(packet.candidates)})"
                )
                detail = pd.DataFrame(
                    [
                        {
                            "Name": c.name,
                            "Email": c.email,
                            "Phone": c.phone,
                            "Score (internal)": c.score if c.score is not None else "—",
                        }
                        for c in packet.candidates
                    ]
                )
                st.dataframe(detail, use_container_width=True, hide_index=True)

        st.subheader("Send")
        test_mode = st.checkbox(
            "Test mode — send all packets to my email (do not mark as sent)",
            value=False,
        )
        test_email = st.text_input(
            "Test recipient email",
            value="shreya@dollfamilyoffice.com",
            disabled=not test_mode,
        )
        redirect = (test_email or "").strip() if test_mode else None

        recipient_check = verify_copy_recipients_for_packets(
            preview.packets, redirect_to=redirect
        )
        configured_bcc = recipient_check["configured_bcc"]
        st.markdown("**Recruiting copy (BCC on live sends)**")
        for required in REQUIRED_PACKET_COPY_EMAILS:
            if required.lower() in {e.lower() for e in configured_bcc}:
                st.success(f"Included: `{required}`")
            else:
                st.error(f"Missing from config: `{required}`")
        if recipient_check["test_mode"]:
            st.warning(
                "Test mode: BCC is disabled. Packets go only to the test recipient above."
            )
        elif recipient_check["all_ok"]:
            st.success(
                f"Verified: both recruiting addresses are BCC’d on all "
                f"{len(preview.packets)} live packet email(s)."
            )
        elif recipient_check["packets_missing"]:
            st.error(
                "Some packets would omit a required BCC "
                "(usually because that address is already the To/manager)."
            )
            for row in recipient_check["packets_missing"]:
                st.write(
                    f"• {row['market']} → `{row['manager']}` missing "
                    f"{', '.join(row['missing'])}"
                )

        st.subheader("Email preview")
        packet_labels = [
            f"{p.market} → {p.manager_email} ({len(p.candidates)})"
            for p in preview.packets
        ]
        chosen_label = st.selectbox(
            "Preview which packet email",
            options=packet_labels,
            key=f"manager_packet_email_preview_{preview.export_batch}",
        )
        chosen = next(
            p
            for p, label in zip(preview.packets, packet_labels)
            if label == chosen_label
        )
        email_preview = preview_packet_email(chosen, redirect_to=redirect)

        st.markdown(f"**To:** `{email_preview.to_email}`")
        if email_preview.bcc_emails:
            st.markdown(
                "**BCC (hidden from GM, both must receive a copy):** "
                + ", ".join(f"`{e}`" for e in email_preview.bcc_emails)
            )
        else:
            st.markdown("**BCC:** _(none — test mode)_")
        st.markdown(f"**Attachment:** `{email_preview.attachment_name}`")
        st.markdown(f"**Subject:** {email_preview.subject}")
        st.text_area(
            "Body",
            value=email_preview.body,
            height=320,
            key=f"manager_packet_email_body_{preview.export_batch}_{chosen_label}",
        )

        ready = outbound_sends_enabled() and sendgrid_configured() and tracking_available(sb)
        test_ready = outbound_sends_enabled() and sendgrid_configured()
        if not outbound_sends_enabled():
            st.warning("Outbound sends are OFF (`OUTBOUND_SENDS_ENABLED=false`).")
        elif not sendgrid_configured():
            st.warning("Configure SendGrid before sending.")
        elif not tracking_available(sb):
            st.warning("Apply the manager packet send-log migration before real sends.")

        live_blocked = (not test_mode) and (
            bool(recipient_check["missing_from_config"])
            or bool(recipient_check["packets_missing"])
        )
        send_label = "Send test packets to me" if test_mode else "Send to managers"
        send_disabled = ((not test_ready) if test_mode else (not ready)) or live_blocked
        if live_blocked:
            st.error(
                "Live send is blocked until both recruiting BCC addresses are configured "
                f"({', '.join(REQUIRED_PACKET_COPY_EMAILS)})."
            )

        if st.button(send_label, type="primary", disabled=send_disabled):
            if test_mode and not redirect:
                st.error("Enter a test recipient email.")
            else:
                with st.spinner("Building zips and emailing…"):
                    successes, errors = send_all_packets(
                        sb,
                        preview.packets,
                        redirect_to=redirect,
                        record_sends=not test_mode,
                    )
                if successes:
                    st.success(f"Sent {len(successes)} packet(s).")
                    for line in successes:
                        st.write(f"✓ {line}")
                if errors:
                    st.error(f"{len(errors)} packet(s) failed:")
                    for line in errors:
                        st.write(f"• {line}")
                if successes and not test_mode:
                    st.session_state.pop("manager_packet_preview", None)
                    st.session_state.pop("manager_packet_preview_batch", None)
                    st.rerun()

st.divider()
st.subheader("Send history")
history = load_recent_sends(sb, limit=100)
if not history:
    st.caption("No manager packet sends logged yet.")
else:
    hist_df = pd.DataFrame(
        [
            {
                "Sent at": str(row.get("sent_at") or "")[:19].replace("T", " "),
                "Name": row.get("candidate_name") or "—",
                "Market": row.get("market") or "—",
                "Manager": row.get("manager_email") or "—",
                "Batch": row.get("export_batch") or "—",
                "Email": row.get("candidate_email") or "—",
            }
            for row in history
        ]
    )
    st.dataframe(hist_df, use_container_width=True, hide_index=True)
