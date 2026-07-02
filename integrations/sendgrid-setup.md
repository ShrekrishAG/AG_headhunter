# SendGrid email setup — Accord Headhunter

Enables **Send email** on the Pipeline page for Round 1 phone screen invites.

## Secrets

```bash
SENDGRID_API_KEY=SG.xxxxxxxx
SENDGRID_FROM_EMAIL=recruiting@weareaccord.com
CALENDLY_R1_URL=https://calendly.com/your-link
```

Optional display name (future template use):

```bash
SENDGRID_FROM_NAME=Accord Group Recruiting
```

## Setup steps

1. [SendGrid](https://sendgrid.com) → **Settings → API Keys** → create key with **Mail Send** permission
2. **Sender Authentication** → verify domain (`weareaccord.com`) or a single **Verified Sender** for MVP
3. Paste API key + from address into `.env`
4. Restart Streamlit

## Test from Pipeline

1. **Communications** page — confirm SendGrid shows ✅
2. **Pipeline** → candidate with email → **Send R1 invite (email)**
3. Edit subject/body → **Send email**

## Compliance (CAN-SPAM)

- Use a real **From** address on your verified domain
- Footer includes **Reply UNSUBSCRIBE** to stop recruiting messages
- Only email candidates who applied (documented in `candidates.source`)

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 403 Forbidden | API key lacks Mail Send permission |
| Bounces | Complete domain authentication (SPF/DKIM) |
| Send disabled | Set `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, and `CALENDLY_R1_URL` |
