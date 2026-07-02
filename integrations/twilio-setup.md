# Twilio SMS setup — Accord Headhunter

Enables **Send SMS** on the Pipeline page for Round 1 phone screen invites.

## Secrets

Add to `dashboard/.env` or Streamlit Secrets:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+19135551234
CALENDLY_R1_URL=https://calendly.com/your-link
```

## Setup steps

1. **Account** — [twilio.com/console](https://www.twilio.com/console) → copy **Account SID** and **Auth Token**
2. **Phone number** — Buy a US number with **SMS** capability (913/816 for KC market)
3. **Trial testing** — Trial accounts can only text **verified** recipient numbers (Console → Verified Caller IDs)
4. **Production** — Register **A2P 10DLC** (Brand + Campaign) before texting real applicants at scale

## Test from Pipeline

1. Open **Communications** page — confirm Twilio shows ✅
2. **Pipeline** → candidate → **Send R1 invite (SMS)**
3. Edit message → **Send SMS**

On success: Twilio returns a message SID; candidate moves to **Outreached** (recruiter sets **Phone screen scheduled** after they book).

## Compliance

- Template includes **Reply STOP to opt out**
- Only text applicants who applied via ZipRecruiter / opted in
- `r1_invite_sent_at` is logged automatically on send

## Troubleshooting

| Error | Fix |
|-------|-----|
| Unverified number | Trial: verify recipient, or upgrade account |
| Send button disabled | Set all Twilio secrets + `CALENDLY_R1_URL`, restart app |
| 30034 campaign | Complete A2P 10DLC registration |
