# Accord Group Recruiting

Resume evaluation and outreach workspace for **Accord Group** TGC sales hiring — ZipRecruiter imports, AI resume scoring, Streamlit pipeline, and SMS/email outreach.

## What it does

1. **Import** resumes exported from ZipRecruiter via `slack-zr-agent`
2. **Score** candidates against the Project Sales Rep scorecard (AI pre-screen)
3. **Review** ranked pipeline in a Streamlit dashboard
4. **Outreach** with bulk SMS/email (Twilio + SendGrid) and Calendly phone screens
5. **Interview** with R1 scorecards (Regional Manager + HR)

## Quick start

### 1. Supabase

Create a Supabase project and run migrations in order:

```bash
# Supabase SQL editor:
supabase/migrations/20260625120000_initial_accord_headhunter_schema.sql
supabase/migrations/20260626180000_update_psr_role_title.sql
supabase/migrations/20260630120000_candidate_activity_tracking.sql
```

### 2. Dashboard

```bash
cd dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build-logo-asset.py
cp .env.example .env   # add Supabase, Twilio, SendGrid, Calendly, OpenAI
streamlit run app.py
```

Opens at http://localhost:8501

### 3. ZipRecruiter exports

**Automatic (recommended):** `slack-zr-agent` runs `post-export-pipeline.py` after each Slack export.

**Manual:**

```bash
python dashboard/scripts/post-export-pipeline.py \
  --export-dir ../slack-zr-agent/exports/YYYY-MM-DD_HHMMSS
```

## Project structure

```
accord-headhunter/
  roles/sales-representative/   # Brief, scorecard, sample walkthrough
  company/context.md            # Accord employer context
  candidates/                   # Scored candidate profiles
  imports/inbox/ZipRecruiter/   # Resume inbox (gitignored — PII)
  dashboard/
    app.py                      # Streamlit app
    views/                      # Pipeline, scoring, communications
    scripts/
      post-export-pipeline.py
      sync-candidates.py
      process-inbox.py
  integrations/                 # Twilio, SendGrid, Calendly setup
  supabase/migrations/
```

## Scorecard

100-point resume rubric for **Project Sales Representative (TGC)**:

| Band | Score | Recommendation |
|------|-------|----------------|
| Strong interview | 85+ | Advance |
| Good candidate | 70–84 | Advance |
| Phone screen | 55–69 | Consider |
| Likely not a fit | &lt;55 | Pass |

See [roles/sales-representative/scorecard.md](roles/sales-representative/scorecard.md).

## Integration with slack-zr-agent

The ZipRecruiter Slack agent (`../slack-zr-agent`) exports CSV + PDFs, then triggers import → prescreen → reference drafts and posts a Slack link to this dashboard.

Set in `slack-zr-agent/.env`:

```bash
ACCORD_HEADHUNTER_DIR=../accord-headhunter
STREAMLIT_APP_URL=https://accord-recruiting.streamlit.app
```

## Deploy

See [dashboard/DEPLOY.md](dashboard/DEPLOY.md) for Streamlit Community Cloud.

## Branding

- Website: https://weareaccord.com
- Theme: Accord green (`#2D5A27`) with oak-tree crest logo

## Security

- Secrets in `dashboard/.env` only (gitignored)
- Raw resumes in `imports/inbox/` are gitignored (PII)
- RLS blocks public Supabase access by design
