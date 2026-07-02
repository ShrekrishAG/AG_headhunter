from __future__ import annotations

import logging
from datetime import datetime, timezone

from playwright.async_api import Page

from zr.browser import ZipRecruiterSessionError
from zr.candidates import Candidate
from zr.projects import Project
from zr.rdb_api import (
    download_resume_pdf,
    ensure_project_session,
    fetch_candidate_info,
    fetch_unlocked_resumes,
)

logger = logging.getLogger(__name__)


async def collect_candidates_for_project(page: Page, project: Project) -> list[Candidate]:
    if not project.project_id:
        raise ZipRecruiterSessionError(
            f"Project {project.name!r} is missing a ZipRecruiter project id."
        )

    await ensure_project_session(page, project.project_id)
    unlocked_items = await fetch_unlocked_resumes(page, project.project_id)
    if not unlocked_items:
        return []

    exported_at = datetime.now(timezone.utc).isoformat()
    candidates: list[Candidate] = []

    for item in unlocked_items:
        resume = item.get("resume") or {}
        jobseeker = resume.get("jobseeker") or {}
        name = str(jobseeker.get("name") or "").strip()
        encrypted_id = str(jobseeker.get("encryptedJobseekerId") or "").strip()
        candidate_id = str(item.get("unlockedResumeId") or resume.get("unlockedResumeId") or "")

        if not name or not encrypted_id:
            continue

        email = ""
        phone = ""
        resume_url = ""

        try:
            info = await fetch_candidate_info(page, encrypted_id)
            detail = ((info.get("unlockedResume") or {}).get("resume") or {})
            contact = detail.get("contactInfo") or {}
            email = str(contact.get("email") or "")
            phone = str(contact.get("phoneNumber") or contact.get("phone") or "")
            resume_url = str(detail.get("tempResumeUrl") or "")
        except Exception as error:
            logger.warning("Could not load contact info for %s: %s", name, error)

        candidates.append(
            Candidate(
                name=name,
                email=email,
                phone=phone,
                project_name=project.name,
                project_id=project.project_id,
                candidate_id=candidate_id,
                resume_url=resume_url,
                exported_at=exported_at,
            )
        )

    return candidates


async def download_candidate_resume(page: Page, candidate: Candidate) -> bytes:
    if not candidate.resume_url:
        raise RuntimeError(f"No resume URL for candidate {candidate.name}")
    return await download_resume_pdf(page, candidate.resume_url)
