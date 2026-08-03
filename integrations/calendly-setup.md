# Calendly setup — Accord Headhunter R1 phone screen

## 1. Outbound booking link (required for SMS/email)

Add to `dashboard/.env` (local) or Streamlit **Secrets** (cloud):

```bash
CALENDLY_R1_URL=https://calendly.com/your-team/project-sales-rep-phone-screen
```

Create the event in Calendly if needed, then paste the link. Invites embed this URL.

## 2. Booking sync → Pipeline (recommended: Supabase Edge Function)

**Free with your existing Supabase project** — no Render card, no Zapier.

→ Full steps: **[calendly-supabase-edge.md](./calendly-supabase-edge.md)**

| Event | Effect |
|-------|--------|
| `invitee.created` | Match by **email** → `r1_scheduled_at` → **Phone screen scheduled** |
| `invitee.canceled` | Clear booking; if scheduled → **Outreached** |

Webhook URL:

```text
https://atrkzqcfdqpefmphtifh.supabase.co/functions/v1/calendly-webhook
```

### SQL (once)

1. `supabase/migrations/20260803180000_calendly_r1_booking.sql`
2. `supabase/migrations/20260803183000_calendly_zapier_rpcs.sql` (RPCs used by the Edge Function)

### Matching tip

Candidates must use the **same email** on Calendly as in Headhunter.

## Pipeline stages (with sync)

1. **Send invite** → **Outreached**
2. **Candidate books on Calendly** → **Phone screen scheduled** + booked date caption
3. **Cancel on Calendly** → booking cleared; stage back to **Outreached** if it was only scheduled

## Alternatives

- **Zapier** (no Calendly API webhooks): [calendly-zapier.md](./calendly-zapier.md)
- **Self-hosted Python** / Render: `webhooks/calendly/`
