# Calendly setup — Accord Headhunter R1 phone screen

## 1. Outbound booking link (required for SMS/email)

Add to `dashboard/.env` (local) or Streamlit **Secrets** (cloud):

```bash
CALENDLY_R1_URL=https://calendly.com/your-team/project-sales-rep-phone-screen
```

Create the event in Calendly if needed, then paste the link. Invites embed this URL.

## 2. Booking sync webhook (Pipeline stage + date)

When a candidate books (or cancels), Calendly POSTs to a small always-on service. The dashboard **does not** receive webhooks itself (Streamlit cannot).

### What it does

| Event | Effect |
|-------|--------|
| `invitee.created` | Match candidate by **email** → set `r1_scheduled_at` → stage **Phone screen scheduled** (from identified / qualified / outreached) |
| `invitee.canceled` | Clear booking fields; if stage was `round_1_scheduled`, revert to **Outreached** |

Pipeline shows a caption under Stage, e.g. `Booked Tue Aug 5, 2:00 PM CT`. Activity timeline logs Calendly booked / canceled.

### Database

Run once in Supabase SQL editor:

`supabase/migrations/20260803180000_calendly_r1_booking.sql`

Or check:

```bash
cd dashboard && python scripts/apply-calendly-booking-migration.py
```

### Run the webhook service

**Production (recommended): Render**

See `webhooks/calendly/RENDER.md`. Repo root `render.yaml` deploys **accord-calendly-webhook**.

Webhook URL after deploy:

```text
https://accord-calendly-webhook.onrender.com/webhooks/calendly
```

**Local**

```bash
cd webhooks/calendly
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Uses dashboard/.env for SUPABASE_* and CALENDLY_WEBHOOK_SIGNING_KEY
uvicorn app:app --host 0.0.0.0 --port 8089
```

Health check: `GET http://localhost:8089/health`  
Endpoint: `POST http://localhost:8089/webhooks/calendly`

Expose locally with HTTPS (ngrok) only if you are not using Render yet:

```bash
ngrok http 8089
# → https://xxxx.ngrok-free.app/webhooks/calendly
```

### Subscribe in Calendly (API)

Webhooks are a **paid Calendly** feature. Create a personal access token, then:

```bash
# dashboard/.env
CALENDLY_PAT=...
CALENDLY_WEBHOOK_URL=https://xxxx.ngrok-free.app/webhooks/calendly
CALENDLY_ORGANIZATION_URI=https://api.calendly.com/organizations/XXXX
# or CALENDLY_USER_URI=https://api.calendly.com/users/XXXX

cd dashboard && python scripts/create-calendly-webhook.py
```

Store the printed `signing_key`:

```bash
CALENDLY_WEBHOOK_SIGNING_KEY=...
```

Restart the webhook process after setting the key.

### Matching tip

Candidates must have the **same email** they use on Calendly. If they book with a different address, the webhook logs `candidate_not_found` and leaves Pipeline unchanged (manual stage still works).

## Pipeline stages (with sync)

1. **Send invite** → **Outreached**
2. **Candidate books on Calendly** → **Phone screen scheduled** + booked date caption
3. **Cancel on Calendly** → booking cleared; stage back to **Outreached** if it was only scheduled

## Local smoke test (no Calendly signature)

```bash
CALENDLY_SKIP_SIGNATURE_VERIFY=true uvicorn app:app --port 8089
curl -s -X POST http://localhost:8089/webhooks/calendly \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "invitee.created",
    "payload": {
      "email": "candidate@example.com",
      "name": "Test Candidate",
      "uri": "https://api.calendly.com/scheduled_events/AAA/invitees/BBB",
      "scheduled_event": {
        "uri": "https://api.calendly.com/scheduled_events/AAA",
        "start_time": "2026-08-10T19:00:00.000000Z"
      }
    }
  }'
```
