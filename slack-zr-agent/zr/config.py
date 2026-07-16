import os
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def bot_relative_path(value: Optional[Union[str, Path]], default: Path) -> Path:
    """Resolve env paths relative to slack-zr-agent root (not process cwd)."""
    path = Path(value) if value else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def accord_headhunter_root() -> Path:
    raw = os.getenv("ACCORD_HEADHUNTER_DIR", "..").strip() or ".."
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
ALLOWED_SLACK_USER_ID = os.getenv("ALLOWED_SLACK_USER_ID", "")
SLACK_NOTIFY_USER_ID = os.getenv("SLACK_NOTIFY_USER_ID") or ALLOWED_SLACK_USER_ID

SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "true").lower() == "true"
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "8"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))

ZIPRECRUITER_BASE_URL = os.getenv("ZIPRECRUITER_BASE_URL", "https://www.ziprecruiter.com")
ZIPRECRUITER_RDB_URL = os.getenv(
    "ZIPRECRUITER_RDB_URL",
    "https://www.ziprecruiter.com/emp/rdb/dashboard/active_projects",
)

BROWSER_DATA_DIR = bot_relative_path(os.getenv("BROWSER_DATA_DIR"), BASE_DIR / "browser-data")
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
PLAYWRIGHT_CHANNEL = os.getenv("PLAYWRIGHT_CHANNEL", "chrome")
CHROME_CDP_URL = os.getenv("CHROME_CDP_URL", "")

EXPORT_BASE_DIR = bot_relative_path(os.getenv("EXPORT_BASE_DIR"), BASE_DIR / "exports")

ACCORD_HEADHUNTER_DIR = os.getenv("ACCORD_HEADHUNTER_DIR", "").strip()
PIPELINE_REVIEW_POOL = int(os.getenv("PIPELINE_REVIEW_POOL", "25"))
DEFAULT_ROLE_SLUG = os.getenv("DEFAULT_ROLE_SLUG", "sales-representative").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_PRESCREEN_MODEL = os.getenv("OPENAI_PRESCREEN_MODEL", "gpt-4o-mini")

LOGIN_TIMEOUT_MS = 120_000
NAVIGATION_TIMEOUT_MS = 60_000
