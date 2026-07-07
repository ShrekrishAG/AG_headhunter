# Heymarket SMS setup — Accord Headhunter

Outbound SMS from the Pipeline page. Inbound replies are handled in the [Heymarket console](https://app.heymarket.com).

## Where to get credentials (Heymarket app)

1. Open **https://app.heymarket.com/admin/integrations/api**
2. Click **Create API Secret** (recommended) or copy the **legacy API key**

## Which ID goes where (`dashboard/.env`)

| `.env` variable | Heymarket source | Example |
|-----------------|------------------|---------|
| `HEYMARKET_API_SECRET_ID` | API page → Secret ID | `abc123-secret-id` |
| `HEYMARKET_API_SECRET_KEY` | API page → Secret Key (shown **once**) | long random string |
| `HEYMARKET_API_KEY` | API page → legacy team key (optional instead of secret) | `hm_...` |
| `HEYMARKET_INBOX_ID` | `GET /v1/inboxes` → `id` of your recruiting inbox | `12345` |
| `HEYMARKET_CREATOR_ID` | `GET /v1/team` → **your** user `id` in `members` | `67890` |

Also required (unchanged):

| Variable | Source |
|----------|--------|
| `CALENDLY_R1_URL` | Your Calendly booking link |
| `OUTBOUND_SENDS_ENABLED=true` | Enables Send SMS on Pipeline |

You do **not** put the sending phone number in `.env` — Heymarket uses the phone tied to `HEYMARKET_INBOX_ID`.

## Matching inbox + creator from API JSON

After `curl ... /v1/inboxes`:

```json
{
  "id": 12345,
  "name": "Recruiting",
  "phones": ["+18333709717"],
  "members": [67890, 11111]
}
```

→ `HEYMARKET_INBOX_ID=12345`

After `curl ... /v1/team`, find **your** email/name:

```json
{ "id": 67890, "name": "Shreya", "email": "you@..." }
```

→ `HEYMARKET_CREATOR_ID=67890` (must also appear in that inbox's `members` list)

## List IDs locally

```bash
cd accord-headhunter/dashboard && source .venv/bin/activate
python scripts/verify-heymarket.py
```

## Streamlit Cloud

Add the same keys to **Secrets** (TOML), not only local `.env`.
