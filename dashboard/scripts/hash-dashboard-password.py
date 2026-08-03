#!/usr/bin/env python3
"""Hash a dashboard password for HEADHUNTER_USERS (pbkdf2).

Usage:
  python scripts/hash-dashboard-password.py 'your-password'
  python scripts/hash-dashboard-password.py   # prompts securely
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.auth import hash_password  # noqa: E402


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Password: ")
    if not password:
        raise SystemExit("Password required.")
    hashed = hash_password(password)
    username = (sys.argv[2] if len(sys.argv) > 2 else "user").strip().lower()
    name = sys.argv[3] if len(sys.argv) > 3 else username.title()
    print(hashed)
    print()
    print("Example HEADHUNTER_USERS JSON entry:")
    print(
        json.dumps(
            [{"username": username, "name": name, "password_hash": hashed}],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
