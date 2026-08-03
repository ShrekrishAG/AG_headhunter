# Render — Calendly webhook

Deploys `webhooks/calendly` as an always-on HTTPS service so Calendly can POST bookings.

## One-time deploy

1. Push this repo to GitHub (`ShrekrishAG/AG_headhunter`).
2. Open [Render Blueprints](https://dashboard.render.com/blueprints) → **New Blueprint Instance**.
3. Connect the repo → Render reads `render.yaml` → creates **accord-calendly-webhook**.
4. When prompted, set secrets:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `CALENDLY_WEBHOOK_SIGNING_KEY` (from Calendly after you create the subscription — can set a placeholder first, update after)
5. Deploy. Service URL looks like:
   `https://accord-calendly-webhook.onrender.com`

## After deploy

1. Run the Supabase migration (`20260803180000_calendly_r1_booking.sql`) if not done.
2. Create the Calendly webhook subscription pointing at:
   ```
   https://accord-calendly-webhook.onrender.com/webhooks/calendly
   ```
   ```bash
   # dashboard/.env
   CALENDLY_PAT=...
   CALENDLY_WEBHOOK_URL=https://accord-calendly-webhook.onrender.com/webhooks/calendly
   CALENDLY_ORGANIZATION_URI=https://api.calendly.com/organizations/...
   cd dashboard && python scripts/create-calendly-webhook.py
   ```
3. Paste the printed signing key into Render → Environment → `CALENDLY_WEBHOOK_SIGNING_KEY` → **Save** (redeploys).
4. Check `https://accord-calendly-webhook.onrender.com/health`

## Plan note

`render.yaml` uses **starter** (always on). Free tier sleeps and will miss Calendly events until wake — fine for a quick test only; use starter for real recruiting.

## Manual (no Blueprint)

- **Root directory:** leave blank (repo root)
- **Build:** `pip install -r webhooks/calendly/requirements.txt`
- **Start:** `cd webhooks/calendly && uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Health:** `/health`
