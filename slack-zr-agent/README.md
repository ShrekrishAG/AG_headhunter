# Slack ZipRecruiter Agent

Slack bot that asks for your permission before logging into ZipRecruiter and listing your Resume Database projects.

## What it does

1. Sends a Slack message (scheduled or via `/zr-projects`)
2. Asks: **"Can I log into your ZipRecruiter account?"**
3. On **Yes, login** → uses a saved browser session to open Resume Database
4. Lists your projects back in Slack

## Prerequisites

- Python 3.11+
- A Slack workspace where you can install apps
- ZipRecruiter employer account with Resume Database access

## 1. Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it e.g. `ZipRecruiter Agent`
3. Under **OAuth & Permissions** → **Bot Token Scopes**, add:
   - `chat:write`
   - `files:write`
   - `im:write`
   - `commands`
   - `app_mentions:read`
   - `im:history`
   - `im:read`
4. Under **Socket Mode** → enable Socket Mode
5. Under **Basic Information** → **App-Level Tokens** → create a token with `connections:write`
6. Under **Slash Commands** → create:
   - `/zr-projects` (or `/zr-project` — both work)
   - `/zr-export`
   - `/zr-review`
7. Under **Event Subscriptions** → enable and subscribe to bot events:
   - `app_mention`
   - `message.im`
8. Under **Interactivity & Shortcuts** → turn **ON** (required for Yes/No buttons)
9. **Install App** to workspace — reinstall after changing scopes or events
9. Copy:
   - **Bot User OAuth Token** (`xoxb-...`)
   - **Signing Secret**
   - **App-Level Token** (`xapp-...`)

## 2. Configure environment

```bash
cd slack-zr-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env`:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
ALLOWED_SLACK_USER_ID=U...   # your Slack member ID
```

Find your Slack member ID: click your profile → ⋮ → **Copy member ID**

## 3. Log into ZipRecruiter once

### Option A — standard login (try this first)

```bash
python login.py
```

A Chrome window opens. If you see **"Performing security verification"**:
1. Click **Verify you are human**
2. Wait for the page to load
3. Log into ZipRecruiter
4. Open **Resume Database**
5. Press Enter in the terminal

### Option B — if Cloudflare keeps blocking (recommended)

Use your **real Chrome** instead of Playwright's browser:

**Terminal 1** — start Chrome with remote debugging:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$(pwd)/browser-data"
```

In that Chrome window:
1. Go to https://www.ziprecruiter.com
2. Complete Cloudflare + log in
3. Open Resume Database

**Terminal 2** — connect and save:
```bash
python login.py --cdp
```

Add to `.env` so the Slack agent uses the same Chrome session:
```bash
CHROME_CDP_URL=http://localhost:9222
```

> Keep that Chrome window open while the Slack agent runs, or reuse the same `browser-data` profile.

## 4. Run the agent

```bash
python main.py
```

## Usage

### Manual trigger
In Slack DM with the bot or any channel where it's invited:

```
/zr-projects
```

Or mention the bot:
```
@ZipRecruiter Agent list my projects
```

### Export candidates (CSV + resumes)

After listing projects, click **Export candidates (CSV + resumes)**. A form lets you set:

- **Default limit per project** — e.g. `5` exports up to 5 candidates from every project
- **Per-project overrides** — one line per project, e.g. `Accord Seattle=10`

Leave both empty to export all unlocked candidates.

Other ways to trigger export:

```
/zr-export 5
export 5 candidates per project
export candidates: Accord Seattle=10, Accord NYC=5
```

Slash command and DM text support the same limit syntax.

### Review locked pipeline → unlock top N → export

Score locked candidates using visible profile text (work experience), then confirm before spending unlock credits.

**Form (recommended):** run `/zr-review` with no arguments, or click **Review locked pipeline** after listing projects. Set:

- **Unlock top N per project** — e.g. `10` unlocks the top 10 from each project
- **Review pool per project** — how many locked profiles to score first (default 25)
- **Per-project overrides** — e.g. `TGC St Louis=10` on its own line

**Text commands** still work:

```
/zr-review 5 in TGC St Louis
review top 10 per project
review 25 locked candidates in Accord NYC
```

Flow:

1. Opens the project **Sourcing** tab (`/emp/rdb/project/{id}/sourcing`) and reviews up to `PIPELINE_REVIEW_POOL` locked profiles (default 25)
2. AI-scores each against the Accord resume rubric (`OPENAI_API_KEY` from `.env` or `dashboard/.env`)
3. Posts top N with scores in Slack
4. **Yes, unlock N** → clicks Connect on ZipRecruiter (N credits)
5. **Export & sync** → CSV + resumes + post-export pipeline (import, prescreen, reference drafts)

Requires `ACCORD_HEADHUNTER_DIR` pointing at the monorepo root. Set `PIPELINE_REVIEW_POOL=25` in `.env` to change how many locked profiles are scored.

Exports are saved locally under `exports/YYYY-MM-DD_HHMMSS/`:

```
exports/2026-06-16_143022/
  candidates.csv
  resumes/
    001_Jane_Doe_Project_Name.pdf
    002_John_Smith_Project_Name.pdf
```

The CSV includes: name, email, phone, project name, project id, candidate id, resume filename, exported timestamp.

Terminal-only export (no Slack):

```bash
python export_candidates.py
python export_candidates.py --limit 5
python export_candidates.py --project-limit "Accord Seattle=10" --project-limit "Accord NYC=5"
```

Optional: set a custom export folder in `.env`:

```bash
EXPORT_BASE_DIR=./exports
```

### Scheduled daily prompt
Enabled by default at 8:00 AM server time. Configure in `.env`:

```bash
SCHEDULE_ENABLED=true
SCHEDULE_HOUR=8
SCHEDULE_MINUTE=0
SLACK_NOTIFY_USER_ID=U...
```

## Project structure

```
slack-zr-agent/
  main.py              # Starts Slack bot + scheduler
  login.py             # One-time ZipRecruiter login
  export_candidates.py # Terminal export (CSV + resumes)
  slack_app/
    handlers.py        # Slack commands, buttons, events
    messages.py        # Block Kit UI
  zr/
    browser.py         # Playwright session
    projects.py        # Project list scraper
    candidates.py      # Unlocked candidate scraper
    export.py          # CSV + resume download
    locked_pipeline.py # Locked pipeline scrape + unlock
    pipeline_prescreen.py
    pipeline_review.py
    review_options.py
    config.py
  browser-data/        # Saved login cookies (gitignored)
  exports/             # Exported CSV + resumes (gitignored)
```

## Security

- Only `ALLOWED_SLACK_USER_ID` can approve login
- Agent never runs without clicking **Yes, login**
- No ZipRecruiter password stored in code
- Session cookies live in `browser-data/` locally

## Troubleshooting

**"/zr-project failed because the app did not respond"**
→ Restart the agent: `Ctrl+C` then `python main.py`. Use `/zr-projects` or `/zr-project`.

**Typing "list my projects" does nothing**
→ In Slack app settings: **Event Subscriptions** → subscribe to `message.im` → reinstall app → restart `python main.py`.

**"Sending messages to this app has been turned off"**
→ **App Home** → turn on "Allow users to send Slash commands and messages from the messages tab".

**"Performing security verification" / Cloudflare bot check**
→ Complete the checkbox in the browser window, or use `python login.py --cdp` with real Chrome (see README Option B)

**"ZipRecruiter session is not active"**
→ Run `python login.py` again

**"No projects were found"**
→ ZipRecruiter may have changed their UI. Open Resume Database manually, check DevTools → Network for a projects API call, and share the URL so we can refine the scraper.

**Slack buttons do nothing**
→ Confirm Socket Mode is enabled and `SLACK_APP_TOKEN` is set. Restart `python main.py`.

**Scheduled prompt not arriving**
→ Bot must be running (`python main.py`). For production, deploy to Railway/Fly and keep the process alive.

## Next steps (v2)

- AI parse/filter resumes
- GM approval dashboard by location
- Upload exports to Google Drive automatically
