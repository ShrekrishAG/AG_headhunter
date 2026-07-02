# Accord Recruiting Dashboard

Streamlit scoring app for **Accord Group** TGC sales recruiting — evaluates ZipRecruiter resume exports.

## Pages

| Page | Purpose |
|------|---------|
| **Pipeline** | All candidates grouped by stage, agent rank, and market |
| **R1 Scoring** | Regional Manager & HR fill independent phone screen scorecards |
| **Process** | Hiring workflow overview |
| **Job description** | Sales Representative role brief |

## Setup

```bash
cd dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build-logo-asset.py
cp .env.example .env
```

Add your **service role key** to `.env` (Settings → API in Supabase). Do not use the anon key — RLS blocks public access by design.

```bash
streamlit run app.py
```

## ZipRecruiter import

```bash
python scripts/import-ziprecruiter-export.py --latest
python scripts/sync-candidates.py
```

## R1 scorecard

Mirrors `roles/sales-representative/scorecard.md`:

- 6 dimensions scored 1–4 with weights (auto weighted total)
- 4 must-have gates (license, work auth, employment history, market willingness)
- Advance / Hold / Pass vote per interviewer
- Panel summary when both interviewers have submitted

## Schema

Migration: `supabase/migrations/20260625120000_initial_accord_headhunter_schema.sql`

Tables: `roles`, `candidates`, `r1_evaluations`

Extra candidate fields: `market`, `ziprecruiter_project_id`, `phone`, `resume_url`, `avatar_url`

## Candidate sync pipeline

```bash
python scripts/sync-candidates.py
```

1. `process-inbox.py` — import new resumes
2. `agent-prescreen-unscored.py` — score unscored profiles (needs `OPENAI_API_KEY`)
3. `upload-resumes.py` · `sync-avatars.py` · `backfill-candidate-contacts.py`
4. `sync-agent-stages.py` — push scores/stages to Supabase for Pipeline ranking
