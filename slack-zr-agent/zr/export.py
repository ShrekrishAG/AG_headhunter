from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

from zr.browser import ZipRecruiterSessionError, ensure_logged_in, ziprecruiter_context
from zr.candidate_export import collect_candidates_for_project, download_candidate_resume
from zr.candidates import Candidate
from zr.config import EXPORT_BASE_DIR
from zr.export_options import ExportOptions
from zr.projects import fetch_projects_on_page
from zr.rdb_api import validate_rdb_api_access
from zr.utils import sanitize_filename, timestamp_folder_name

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    export_dir: Path
    csv_path: Path
    resumes_dir: Path
    candidate_count: int
    resume_count: int
    projects_processed: int
    options: ExportOptions | None = None
    skipped_projects: list[str] = field(default_factory=list)


def _build_resume_filename(index: int, candidate: Candidate) -> str:
    name = sanitize_filename(candidate.name, "candidate")
    project = sanitize_filename(candidate.project_name, "project")
    return f"{index:03d}_{name}_{project}.pdf"


async def _download_resume(page: Page, candidate: Candidate, dest_path: Path) -> bool:
    if not candidate.resume_url:
        return False
    try:
        dest_path.write_bytes(await download_candidate_resume(page, candidate))
        return True
    except Exception:
        return False


def _write_csv(csv_path: Path, candidates: list[Candidate]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "email",
                "phone",
                "project_name",
                "project_id",
                "candidate_id",
                "resume_filename",
                "exported_at",
            ],
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "name": candidate.name,
                    "email": candidate.email,
                    "phone": candidate.phone,
                    "project_name": candidate.project_name,
                    "project_id": candidate.project_id,
                    "candidate_id": candidate.candidate_id,
                    "resume_filename": candidate.resume_filename,
                    "exported_at": candidate.exported_at,
                }
            )


async def export_all_candidates(options: ExportOptions | None = None) -> ExportResult:
    export_options = options or ExportOptions()
    export_dir = EXPORT_BASE_DIR / timestamp_folder_name()
    resumes_dir = export_dir / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)
    csv_path = export_dir / "candidates.csv"

    all_candidates: list[Candidate] = []
    resume_count = 0
    projects_processed = 0
    skipped_projects: list[str] = []

    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        project_result = await fetch_projects_on_page(page)
        projects = [
            project
            for project in project_result.projects
            if project.unlocked_count not in (None, 0)
            and export_options.should_export_project(project)
        ]

        if not projects:
            raise ZipRecruiterSessionError(
                "No matching projects with unlocked candidates were found to export."
            )

        await validate_rdb_api_access(page, projects[0].project_id)

        for project in projects:
            if not project.project_id:
                skipped_projects.append(project.name)
                continue

            try:
                candidates = await collect_candidates_for_project(page, project)
            except ZipRecruiterSessionError as error:
                logger.warning("Skipping project %s: %s", project.name, error)
                skipped_projects.append(project.name)
                continue

            candidates = export_options.apply_to_candidates(project, candidates)
            if not candidates:
                continue

            projects_processed += 1
            for candidate in candidates:
                index = len(all_candidates) + 1
                filename = _build_resume_filename(index, candidate)
                resume_path = resumes_dir / filename
                if await _download_resume(page, candidate, resume_path):
                    candidate.resume_filename = filename
                    resume_count += 1
                all_candidates.append(candidate)

    if not all_candidates:
        if skipped_projects:
            raise ZipRecruiterSessionError(
                "Could not open any projects for export: "
                + ", ".join(skipped_projects)
            )
        raise ZipRecruiterSessionError(
            "Projects were found, but no unlocked candidate contact details could be exported. "
            "This usually means ZipRecruiter blocked the export API. "
            "Run `python login.py`, complete any Cloudflare check, then try again."
        )

    _write_csv(csv_path, all_candidates)

    return ExportResult(
        export_dir=export_dir,
        csv_path=csv_path,
        resumes_dir=resumes_dir,
        candidate_count=len(all_candidates),
        resume_count=resume_count,
        projects_processed=projects_processed,
        options=export_options,
        skipped_projects=skipped_projects,
    )


def format_export_for_slack(result: ExportResult) -> str:
    limit_line = ""
    if result.options:
        limit_line = f"• {result.options.summary_line()}\n"

    skipped_line = ""
    if result.skipped_projects:
        skipped_line = (
            f"• Skipped projects: {', '.join(result.skipped_projects)}\n"
        )

    return (
        "*Export complete*\n\n"
        f"{limit_line}"
        f"• Candidates exported: *{result.candidate_count}*\n"
        f"• Resumes downloaded: *{result.resume_count}*\n"
        f"• Projects processed: *{result.projects_processed}*\n"
        f"{skipped_line}"
        f"• Local export folder: `{result.export_dir}`\n"
        f"• CSV: `{result.csv_path}`\n"
        f"• Resumes folder: `{result.resumes_dir}`"
    )
