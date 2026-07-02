# Deploy to Streamlit Community Cloud

Public recruiting dashboard — share page links with your hiring team.

## 1. Push to GitHub

Create a **new** private repo (e.g. `accord-headhunter`) — not linked to any other headhunter project.

```bash
git remote add origin https://github.com/ShrekrishAG/AG_headhunter.git
git push -u origin main
```

## 2. Create the app

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub
2. **Create app**
3. **Repository:** `ShrekrishAG/AG_headhunter`
4. **Branch:** `main`
5. **Main file path:** `dashboard/app.py`
6. **App URL slug:** e.g. `accord-recruiting` → **https://accord-recruiting.streamlit.app**

Or open the prefilled deploy link:

```bash
./dashboard/scripts/open-streamlit-deploy.sh
```

Streamlit uses `dashboard/requirements.txt` and `dashboard/.streamlit/config.toml`.

## 3. Settings

In Streamlit Cloud → **Manage app** → **Settings**:

1. **Sharing** → **Public** or private link per your policy
2. **Secrets** → paste credentials in **TOML** format (not `.env`)

Generate from local `.env`:

```bash
cd dashboard && python3 scripts/print-streamlit-secrets.py
```

Minimum secrets:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your_service_role_key"
CALENDLY_R1_URL = "https://calendly.com/..."
OUTBOUND_SENDS_ENABLED = "true"
TWILIO_ACCOUNT_SID = "AC..."
TWILIO_AUTH_TOKEN = "..."
TWILIO_FROM_NUMBER = "+1..."
SENDGRID_API_KEY = "SG...."
SENDGRID_FROM_EMAIL = "..."
SENDGRID_FROM_NAME = "Accord Group Recruiting"
OPENAI_API_KEY = "sk-..."   # optional if REDRAFT_MODE=template
```

## 4. Deploy

Click **Deploy**. First build takes ~2–3 minutes.

## 5. Page links

| Page | URL |
|------|-----|
| Pipeline (default) | `https://accord-recruiting.streamlit.app/` |
| Dashboard | `https://accord-recruiting.streamlit.app/dashboard` |
| Process | `https://accord-recruiting.streamlit.app/process` |
| Communications | `https://accord-recruiting.streamlit.app/communications` |
| R1 Scoring | `https://accord-recruiting.streamlit.app/r1-scoring` |

Set `STREAMLIT_APP_URL` in `.env` and `slack-zr-agent/.env` to match.

## Updates

Push to `main` → Streamlit Cloud redeploys automatically.

## Local vs Cloud

| | Local | Cloud |
|---|-------|-------|
| Credentials | `dashboard/.env` | Streamlit Secrets (TOML) |
| Post-export pipeline | Same machine as `slack-zr-agent` | Cloud app only — run pipeline on a worker or locally |

## Security

- Service role key is server-side only (never in the browser)
- Keep the GitHub repo **private** if `candidates/` contains PII
- Raw exports stay gitignored under `imports/inbox/`
