#!/usr/bin/env python3
"""Print Streamlit Cloud secrets TOML from dashboard/.env (for paste into Cloud UI)."""

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

required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
missing = [k for k in required if not values.get(k)]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")

print("# Paste into Streamlit Cloud → Settings → Secrets\n")
for key in required:
    val = values[key].replace('"', '\\"')
    print(f'{key} = "{val}"')
