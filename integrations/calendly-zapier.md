# Calendly → Zapier → Supabase (recommended, free)

No Render / hosted webhook. Zapier listens to Calendly and calls Supabase RPCs that update Pipeline.

## What you get

| Calendly event | Pipeline effect |
|----------------|-----------------|
| Invitee Created | Match by email → `r1_scheduled_at` + stage **Phone screen scheduled** |
| Invitee Canceled | Clear booking; if stage was scheduled → **Outreached** |

Pipeline shows `Booked …` under Stage (same as before).

## 1. Run SQL in Supabase (once)

In **Supabase → SQL Editor**, run both files in order:

1. `supabase/migrations/20260803180000_calendly_r1_booking.sql` (columns)
2. `supabase/migrations/20260803183000_calendly_zapier_rpcs.sql` (RPCs for Zapier)

## 2. Gather credentials

From **Supabase → Project Settings → API**:

- Project URL — e.g. `https://xxxx.supabase.co`
- **service_role** key (secret — only paste into Zapier)

## 3. Zap A — booking created

1. [zapier.com](https://zapier.com) → **Create Zap**
2. **Trigger:** Calendly → **Invitee Created**  
   Connect your Calendly account; pick the phone-screen event type (or all events).
3. **Action:** Webhooks by Zapier → **Custom Request**

| Field | Value |
|-------|--------|
| Method | POST |
| URL | `https://YOUR_PROJECT.supabase.co/rest/v1/rpc/apply_calendly_booking` |
| Data Pass-Through? | No |
| Unflatten | Yes |

**Headers** (one per line in Zapier, or key/value pairs):

```
apikey: YOUR_SERVICE_ROLE_KEY
Authorization: Bearer YOUR_SERVICE_ROLE_KEY
Content-Type: application/json
Prefer: return=representation
```

**Data** (JSON body) — map Calendly fields from the trigger:

```json
{
  "p_email": "INVITEE_EMAIL_FROM_CALENDLY",
  "p_start_time": "EVENT_START_TIME_FROM_CALENDLY",
  "p_invitee_uri": "INVITEE_URI_OPTIONAL",
  "p_event_uri": "EVENT_URI_OPTIONAL"
}
```

In the Zapier UI, use the field picker instead of typing — typical names:

- `p_email` ← **Invitee Email**
- `p_start_time` ← **Event Start Time** (ISO timestamp)
- `p_invitee_uri` ← Invitee URI / Cancel URL source if available (optional)
- `p_event_uri` ← Event URI (optional)

4. Test → you should see `"ok": true` and a `candidate_id` if that email exists in Pipeline.
5. Publish.

## 4. Zap B — booking canceled

Same pattern:

- **Trigger:** Calendly → **Invitee Canceled**
- **Action:** Webhooks → POST  
  `https://YOUR_PROJECT.supabase.co/rest/v1/rpc/apply_calendly_cancel`

Body:

```json
{
  "p_email": "INVITEE_EMAIL",
  "p_invitee_uri": "INVITEE_URI_OPTIONAL"
}
```

## 5. Free-plan notes

- Zapier Free: **100 tasks/month**, 2-step Zaps (trigger + 1 action) — enough for these two Zaps.
- Candidate must book with the **same email** as in Headhunter. Mismatch → RPC returns `candidate_not_found` (safe no-op); set stage manually.
- Never put the service_role key in Streamlit secrets shared widely — Zapier only.

## Smoke test without Calendly

In Supabase SQL editor (replace email with a real Pipeline candidate):

```sql
select public.apply_calendly_booking(
  'candidate@example.com',
  '2026-08-10T19:00:00Z'::timestamptz,
  null,
  null
);
```

Refresh Pipeline — stage + **Booked …** caption should appear.

```sql
select public.apply_calendly_cancel('candidate@example.com', null);
```

## Optional: keep the Python webhook

`webhooks/calendly` + Render remain in the repo as an alternative. Prefer Zapier unless you outgrow the free task limit.
