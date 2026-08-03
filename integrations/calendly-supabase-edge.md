# Calendly → Supabase Edge Function (recommended)

Free with your existing Supabase project. No Render, no Zapier.

When a candidate books/cancels on Calendly, Supabase updates Pipeline:
stage → **Phone screen scheduled** + `Booked …` date (or clears on cancel).

## Prerequisites

1. Run SQL in **Supabase → SQL Editor** (both, in order):
   - `supabase/migrations/20260803180000_calendly_r1_booking.sql`
   - `supabase/migrations/20260803183000_calendly_zapier_rpcs.sql`  
     (RPCs are shared — Edge Function calls them)

2. Install [Supabase CLI](https://supabase.com/docs/guides/cli) (once):
   ```bash
   brew install supabase/tap/supabase
   ```

## Deploy the function

From the repo root:

```bash
cd /path/to/accord-headhunter
supabase login
supabase link --project-ref atrkzqcfdqpefmphtifh
supabase functions deploy calendly-webhook --no-verify-jwt
```

`--no-verify-jwt` is required so Calendly can POST without a Supabase user token  
(also set in `supabase/config.toml` under `[functions.calendly-webhook]`).

## Set the signing secret

After you create the Calendly webhook subscription (below), set:

```bash
supabase secrets set CALENDLY_WEBHOOK_SIGNING_KEY=your_signing_key_here
```

Or: **Supabase Dashboard → Edge Functions → Secrets**.

## Your webhook URL

```text
https://atrkzqcfdqpefmphtifh.supabase.co/functions/v1/calendly-webhook
```

Health check (GET):

```bash
curl -s https://atrkzqcfdqpefmphtifh.supabase.co/functions/v1/calendly-webhook
```

## Point Calendly at it

Calendly **webhook subscriptions are a paid Calendly feature** (API). Create with:

```bash
# dashboard/.env
CALENDLY_PAT=your_personal_access_token
CALENDLY_WEBHOOK_URL=https://atrkzqcfdqpefmphtifh.supabase.co/functions/v1/calendly-webhook
CALENDLY_ORGANIZATION_URI=https://api.calendly.com/organizations/XXXX
# or CALENDLY_USER_URI=...

cd dashboard && python scripts/create-calendly-webhook.py
```

Paste the printed `signing_key` into Supabase secrets (above), then redeploy is **not** required — secrets apply immediately.

Events: `invitee.created`, `invitee.canceled`.

## Smoke test (skip signature)

Temporarily:

```bash
supabase secrets set CALENDLY_SKIP_SIGNATURE_VERIFY=true
```

```bash
curl -s -X POST \
  'https://atrkzqcfdqpefmphtifh.supabase.co/functions/v1/calendly-webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "invitee.created",
    "payload": {
      "email": "EXISTING_CANDIDATE@email.com",
      "uri": "https://api.calendly.com/scheduled_events/AAA/invitees/BBB",
      "scheduled_event": {
        "uri": "https://api.calendly.com/scheduled_events/AAA",
        "start_time": "2026-08-10T19:00:00.000000Z"
      }
    }
  }'
```

Then turn skip off:

```bash
supabase secrets unset CALENDLY_SKIP_SIGNATURE_VERIFY
```

## Dashboard deploy (no CLI)

1. Supabase → **Edge Functions** → **Create a new function** → name `calendly-webhook`
2. Paste `supabase/functions/calendly-webhook/index.ts`
3. Disable **Verify JWT**
4. Deploy + add secret `CALENDLY_WEBHOOK_SIGNING_KEY`

## Alternatives

- Zapier: `integrations/calendly-zapier.md` (if you prefer no Calendly API webhooks)
- Self-hosted Python: `webhooks/calendly/` (needs a paid host or ngrok)
