import re
from datetime import datetime


def sanitize_filename(value: str, fallback: str = "file") -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", (value or fallback).strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or fallback


def timestamp_folder_name() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")
