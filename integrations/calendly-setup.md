# Calendly setup — Accord Headhunter R1 phone screen

The dashboard embeds your **scheduling link** in SMS and email invites. No Calendly API is required for the basic workflow.

## What you need

Add to `dashboard/.env` (local) or Streamlit **Secrets** (cloud):

```bash
CALENDLY_R1_URL=https://calendly.com/your-team/project-sales-rep-phone-screen
```

## Create the event (if you don't have a link yet)

1. Sign in at [calendly.com](https://calendly.com)
2. **Event types** → **+ Create**
3. Name: **Project Sales Rep — Phone Screen** (30 minutes)
4. Location: **Phone call** or **Zoom** (your preference)
5. Set availability for your recruiting team
6. **Copy link** → paste into `CALENDLY_R1_URL`

## Test in the dashboard

1. Restart Streamlit after saving `.env`
2. Open **Pipeline** → expand a candidate → **Send R1 invite (SMS)** or **(email)**
3. The Calendly URL should appear in the message draft
4. **Send** buttons stay disabled until Calendly + Twilio/SendGrid are configured

## Pipeline stages

1. **Send invite** (SMS/email) → candidate moves to **Outreached** (invite sent, awaiting booking)
2. **Recruiter confirms booking** → manually set stage to **Phone screen scheduled**, or use a Calendly webhook (below)
3. Re-sending an invite while already **Outreached** does not change stage — only outreach count increases

## Optional later

- Calendly **webhook** on `invitee.created` → auto-set candidate from `outreached` to `round_1_scheduled` when they book
- Calendly API token for agent automation (not needed for SMS/email invites today)
