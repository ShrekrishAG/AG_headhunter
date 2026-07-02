# Resume import (ZipRecruiter + other sources)

## Inbox layout

```
imports/inbox/
├── ZipRecruiter/          → source: ZipRecruiter (primary)
├── Indeed/                → source: Indeed
├── LinkedIn/              → source: LinkedIn
├── referral/              → source: Referral
└── other/                 → source: Other
```

## ZipRecruiter workflow (recommended)

1. Export candidates from ZipRecruiter via `slack-zr-agent` (Slack bot)
2. The bot auto-runs import → prescreen → reference drafts and posts a Slack review link
3. Or run manually:

```bash
python dashboard/scripts/post-export-pipeline.py --export-dir slack-zr-agent/exports/YYYY-MM-DD_HHMMSS
```

The import script copies resume PDFs and preserves market/project from `candidates.csv`.

## Resume naming convention

Applied automatically by `dashboard/scripts/process-inbox.py`:

```
YYYY-MM-DD-sales-rep-<lastname>-<firstname>.pdf
```

Example: `2026-06-24-sales-rep-borders-kenyan.pdf`

## Manual drop

Place PDFs in the appropriate source subfolder, then:

```bash
python dashboard/scripts/sync-candidates.py
```

## What sync does

1. Rename inbox resumes to standard convention
2. Upsert candidates in Supabase (update if email/slug/LinkedIn already exists)
3. Agent pre-screen unscored candidates (resume → scorecard → `profile.md`)
4. Upload resumes, sync avatars, backfill contacts
5. Sync pipeline stages + ranking from profiles
6. Generate reference outreach drafts for qualified, not-yet-contacted candidates

Set `OPENAI_API_KEY` in `dashboard/.env` for automatic prescreen.

## Privacy

- Raw exports stay in `imports/inbox/` — **gitignored** (PII)
- Only structured profiles in `candidates/` may be committed (review before push)
- Never commit resumes with contact info unless approved
