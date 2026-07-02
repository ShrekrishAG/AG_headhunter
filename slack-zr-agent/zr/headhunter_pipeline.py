"""Run accord-headhunter post-export pipeline and format Slack summaries."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SUMMARY_PREFIX = "PIPELINE_SUMMARY="


def accord_dashboard_dir() -> Path | None:
    configured = os.getenv("ACCORD_HEADHUNTER_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
        dashboard = root / "dashboard" if (root / "dashboard").is_dir() else root
        if dashboard.is_dir():
            return dashboard
    sibling = Path(__file__).resolve().parents[2] / "dashboard"
    if sibling.is_dir():
        return sibling
    return None


def _parse_summary(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(SUMMARY_PREFIX):
            try:
                return json.loads(line[len(SUMMARY_PREFIX) :])
            except json.JSONDecodeError:
                logger.warning("Invalid pipeline summary JSON")
                return None
    return None


def run_post_export_pipeline(export_dir: Path) -> dict | None:
    dashboard = accord_dashboard_dir()
    if not dashboard:
        logger.info("accord-headhunter dashboard not found — skip post-export pipeline")
        return None

    script = dashboard / "scripts" / "post-export-pipeline.py"
    if not script.is_file():
        logger.warning("Missing post-export-pipeline.py at %s", script)
        return None

    venv_python = dashboard / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.is_file() else sys.executable

    logger.info("Running post-export pipeline for %s", export_dir)
    result = subprocess.run(
        [python, str(script), "--export-dir", str(export_dir)],
        cwd=str(dashboard),
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        logger.warning("Post-export pipeline exited %s", result.returncode)

    return _parse_summary(result.stdout or "")


def format_pipeline_slack_message(summary: dict | None, *, export_dir: Path) -> str | None:
    if not summary:
        return None

    streamlit_url = (
        summary.get("streamlit_url")
        or os.getenv("STREAMLIT_APP_URL", "").strip()
        or "http://localhost:8501"
    )
    ready_count = int(summary.get("ready_count") or 0)
    total = summary.get("total_candidates")
    batch = summary.get("export_batch") or export_dir.name
    steps_failed = int(summary.get("steps_failed") or 0)

    lines = [
        f"*ZipRecruiter export synced* — `{batch}`",
    ]
    if total is not None:
        lines.append(f"Pipeline total: *{total}* candidate(s)")
    lines.append(
        f"Ready for outreach review: *{ready_count}* qualified · not contacted"
    )
    if steps_failed:
        lines.append(f":warning: Pipeline finished with *{steps_failed}* step error(s)")

    ready = summary.get("ready") or []
    if ready:
        lines.append("")
        for row in ready[:8]:
            lines.append(
                f"• *{row.get('full_name', '—')}* — "
                f"{row.get('score', '—')}/100 · {row.get('recommendation', '—')}"
            )
        if ready_count > 8:
            lines.append(f"_…and {ready_count - 8} more_")

    lines.extend(
        [
            "",
            f"Review and send in Pipeline: {streamlit_url}",
            "_Reference drafts are saved on each card — compose uses default templates._",
        ]
    )
    return "\n".join(lines)
