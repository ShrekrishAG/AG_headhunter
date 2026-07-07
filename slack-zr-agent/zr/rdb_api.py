from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Page

from zr.browser import ZipRecruiterSessionError
from zr.config import ZIPRECRUITER_BASE_URL

GET_UNLOCKED_RESUMES_URL = (
    f"{ZIPRECRUITER_BASE_URL}/api/rdb2/"
    "employer.rdb2.backend.proto.v1.ResumeAPI/GetUnlockedResumes"
)
GET_CANDIDATE_INFO_URL = (
    f"{ZIPRECRUITER_BASE_URL}/api/rdb2/"
    "employer.rdb2.backend.proto.v1.ResumeAPI/GetCandidateInfo"
)

BROWSER_FETCH_JSON = """
async ({url, payload}) => {
    const response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "include",
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`ZipRecruiter API ${response.status}: ${text.slice(0, 120)}`);
    }
    return await response.json();
}
"""

BROWSER_FETCH_BYTES = """
async (url) => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) {
        throw new Error(`Resume download failed: ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}
"""


def project_pipeline_url(project_id: str) -> str:
    return urljoin(
        ZIPRECRUITER_BASE_URL,
        f"/emp/rdb/project/{project_id}/candidate-pipeline",
    )


def project_sourcing_url(project_id: str) -> str:
    return urljoin(
        ZIPRECRUITER_BASE_URL,
        f"/emp/rdb/project/{project_id}/sourcing",
    )


async def open_sourcing_project(page: Page, project) -> None:
    """Open the Sourcing tab where locked (not yet connected) candidates live."""
    project_id = getattr(project, "project_id", "") or ""
    project_name = getattr(project, "name", "") or "project"
    if not project_id:
        raise ZipRecruiterSessionError(f"Could not open sourcing tab for: {project_name}")

    target = project_sourcing_url(project_id)
    response = await page.goto(target, wait_until="networkidle", timeout=60000)
    if not response or response.status >= 400:
        raise ZipRecruiterSessionError(
            f"Could not open sourcing tab for: {project_name} (HTTP {getattr(response, 'status', '?')})"
        )

    if "/sourcing" not in page.url:
        for label in ("Sourcing",):
            tab = page.get_by_role("tab", name=label).first
            if await tab.count() > 0:
                try:
                    await tab.click(timeout=5000)
                    await page.wait_for_timeout(2000)
                    break
                except Exception:
                    pass

    if "/sourcing" not in page.url and project_id not in page.url:
        raise ZipRecruiterSessionError(
            f"Could not open sourcing tab for: {project_name}. Landed on {page.url}"
        )

    await page.wait_for_timeout(1500)


async def _browser_post_json(page: Page, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await page.evaluate(
        BROWSER_FETCH_JSON,
        {"url": url, "payload": payload},
    )


async def ensure_project_session(page: Page, project_id: str) -> None:
    await page.goto(project_pipeline_url(project_id), wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(1500)


async def validate_rdb_api_access(page: Page, project_id: str) -> None:
    await ensure_project_session(page, project_id)
    try:
        data = await _browser_post_json(
            page,
            GET_UNLOCKED_RESUMES_URL,
            {
                "projectId": project_id,
                "page": 1,
                "pageSize": "PAGE_SIZE_25",
                "includeYes": True,
                "includeMaybe": True,
                "includeNo": True,
                "includeUnrated": True,
            },
        )
    except Exception as error:
        raise ZipRecruiterSessionError(
            "ZipRecruiter blocked candidate export API access. "
            "Run `python login.py`, complete any Cloudflare check, open Resume Database, "
            "then try export again."
        ) from error

    if "unlockedResumes" not in data:
        raise ZipRecruiterSessionError(
            "ZipRecruiter session is active, but candidate export API returned an unexpected response. "
            "Run `python login.py` and try again."
        )


async def fetch_unlocked_resumes(page: Page, project_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page_number = 1

    while True:
        data = await _browser_post_json(
            page,
            GET_UNLOCKED_RESUMES_URL,
            {
                "projectId": project_id,
                "page": page_number,
                "pageSize": "PAGE_SIZE_25",
                "includeYes": True,
                "includeMaybe": True,
                "includeNo": True,
                "includeUnrated": True,
            },
        )
        batch = data.get("unlockedResumes") or []
        if not batch:
            break

        results.extend(batch)
        if len(batch) < 25:
            break
        page_number += 1

    return results


async def fetch_candidate_info(page: Page, encrypted_jobseeker_id: str) -> dict[str, Any]:
    return await _browser_post_json(
        page,
        GET_CANDIDATE_INFO_URL,
        {"encryptedJobseekerId": encrypted_jobseeker_id},
    )


async def download_resume_pdf(page: Page, temp_resume_url: str) -> bytes:
    target = urljoin(ZIPRECRUITER_BASE_URL, temp_resume_url)
    encoded = await page.evaluate(BROWSER_FETCH_BYTES, target)
    body = base64.b64decode(encoded)
    if not body or len(body) < 100:
        raise RuntimeError("Resume download returned empty content")
    return body
