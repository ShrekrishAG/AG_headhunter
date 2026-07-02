"""Communications setup — Calendly, Twilio SMS, SendGrid email."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from lib.communications_status import email_ready, integration_rows, outbound_sends_enabled, sms_ready
from lib.constants import APP_NAME
from lib.r1_invite import get_calendly_r1_url

REPO_ROOT = Path(__file__).resolve().parents[2]

st.title("Communications setup")
st.caption(f"{APP_NAME} · Round 1 invites (SMS + email)")

st.markdown(
    """
Configure **Calendly**, **Twilio**, and **SendGrid** so recruiters can send phone-screen
invites from the **Pipeline** page. Drafts work without these keys; **Send** requires them.
"""
)

rows = integration_rows()
cols = st.columns(3)
for col, row in zip(cols, rows):
    with col:
        icon = "✅" if row["configured"] else "⏳"
        st.metric(row["name"], icon)
        st.caption(row["detail"])
        st.caption(f"_{row['required_for']}_")

st.divider()

if not outbound_sends_enabled():
    st.warning(
        "**Outbound sends are OFF** — Pipeline **Send SMS** and **Send email** buttons are disabled. "
        "Set `OUTBOUND_SENDS_ENABLED=true` in `dashboard/.env` when you are ready to send."
    )
else:
    st.success("Outbound sends are **enabled** on the Pipeline page.")

st.divider()

ready_col1, ready_col2 = st.columns(2)
with ready_col1:
    st.subheader("SMS ready")
    if sms_ready():
        st.success("Twilio + Calendly configured — Send SMS enabled on Pipeline.")
    elif not outbound_sends_enabled():
        st.info("Twilio configured, but sends are disabled (`OUTBOUND_SENDS_ENABLED=false`).")
    else:
        st.warning("Add Twilio credentials and `CALENDLY_R1_URL` to enable Send SMS.")
with ready_col2:
    st.subheader("Email ready")
    if email_ready():
        st.success("SendGrid + Calendly configured — Send email enabled on Pipeline.")
    elif not outbound_sends_enabled():
        st.info("SendGrid configured, but sends are disabled (`OUTBOUND_SENDS_ENABLED=false`).")
    else:
        st.warning("Add SendGrid credentials and `CALENDLY_R1_URL` to enable Send email.")

cal_url = get_calendly_r1_url()
if cal_url:
    st.info(f"**Calendly link in use:** {cal_url}")
else:
    st.info("Paste your Calendly scheduling URL into `CALENDLY_R1_URL` in `dashboard/.env`.")

st.divider()
st.subheader("Local configuration (`dashboard/.env`)")

st.code(
    """# Calendly — your existing phone screen booking link
CALENDLY_R1_URL=https://calendly.com/your-team/your-event

# Twilio SMS
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+19135551234

# SendGrid email
SENDGRID_API_KEY=SG.xxxxxxxx
SENDGRID_FROM_EMAIL=recruiting@weareaccord.com
SENDGRID_FROM_NAME=Accord Group Recruiting""",
    language="bash",
)

st.caption("Restart Streamlit after editing `.env`. On Streamlit Cloud, use **Secrets** (TOML format) instead.")

st.subheader("Setup guides")
for title, rel in [
    ("Calendly", "integrations/calendly-setup.md"),
    ("Twilio SMS", "integrations/twilio-setup.md"),
    ("SendGrid email", "integrations/sendgrid-setup.md"),
]:
    path = REPO_ROOT / rel
    with st.expander(title, expanded=False):
        if path.is_file():
            st.markdown(path.read_text(encoding="utf-8"))
        else:
            st.caption("Guide not found.")

st.divider()
st.subheader("Verify (CLI)")
st.code(
    "cd dashboard && .venv/bin/python scripts/verify-communications.py",
    language="bash",
)

st.markdown(
    """
### Pipeline workflow
1. Score candidates (OpenAI prescreen)
2. Open **Pipeline** → qualified / phone-screen candidates
3. Expand **Send R1 invite (SMS)** or **(email)**
4. Edit copy → optional **Redraft** (OpenAI) → **Send**
"""
)
