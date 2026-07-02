#!/usr/bin/env python3
"""Print Streamlit Cloud secrets TOML from dashboard/.env (paste into Cloud → Settings → Secrets)."""

from __future__ import annotations

from pathlib import Path

env_path = Path(__file__).resolve().parents[1] / ".env"
if not env_path.exists():
    raise SystemExit(f"Missing {env_path}")

values: dict[str, str] = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, val = line.partition("=")
    values[key.strip()] = val.strip().strip('"').strip("'")

# Order matters for readability in the Cloud UI
SECRET_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OUTBOUND_SENDS_ENABLED",
    "CALENDLY_R1_URL",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "SENDGRID_API_KEY",
    "SENDGRID_FROM_EMAIL",
    "SENDGRID_FROM_NAME",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "REDRAFT_MODE",
    "STREAMLIT_APP_URL",
]

required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
missing = [k for k in required if not values.get(k)]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")

print("# Paste into Streamlit Cloud → Manage app → Settings → Secrets\n")
for key in SECRET_KEYS:
    val = values.get(key, "").strip()
    if not val:
        continue
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    print(f'{key} = "{escaped}"')
