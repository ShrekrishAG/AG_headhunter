"""Browse locked pipeline candidates, read profiles, and unlock via Connect."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page, Response

from zr.browser import ZipRecruiterSessionError, ensure_logged_in, ziprecruiter_context
from zr.projects import Project
from zr.rdb_api import open_sourcing_project

logger = logging.getLogger(__name__)

EXPERIENCE_KEYS = (
    "workHistory",
    "employmentHistory",
    "positions",
    "experiences",
    "workExperiences",
)


@dataclass
class LockedCandidate:
    name: str
    pipeline_index: int
    profile_text: str = ""
    headline: str = ""
    location: str = ""
    encrypted_jobseeker_id: str = ""
    is_unlocked: bool = False
    total_score: int | None = None
    recommendation: str | None = None
    summary: str | None = None
    qualifies: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _extract_experience_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    resume = item.get("resume") if isinstance(item.get("resume"), dict) else item
    jobseeker = resume.get("jobseeker") if isinstance(resume.get("jobseeker"), dict) else {}

    headline = (
        jobseeker.get("headline")
        or resume.get("headline")
        or item.get("headline")
        or ""
    )
    if headline:
        parts.append(f"Headline: {headline}")

    location = jobseeker.get("location") or resume.get("location") or item.get("location")
    if isinstance(location, dict):
        location = ", ".join(
            str(location.get(key) or "")
            for key in ("city", "state", "country")
            if location.get(key)
        )
    if location:
        parts.append(f"Location: {location}")

    for container in (resume, jobseeker, item):
        for key in EXPERIENCE_KEYS:
            hist = container.get(key)
            if not isinstance(hist, list):
                continue
            for pos in hist[:12]:
                if not isinstance(pos, dict):
                    continue
                title = pos.get("title") or pos.get("jobTitle") or pos.get("position") or ""
                company = (
                    pos.get("company")
                    or pos.get("employer")
                    or pos.get("companyName")
                    or ""
                )
                desc = pos.get("description") or pos.get("summary") or ""
                dates = pos.get("dateRange") or pos.get("dates") or ""
                if isinstance(dates, dict):
                    dates = " - ".join(
                        str(dates.get(key) or "")
                        for key in ("start", "end")
                        if dates.get(key)
                    )
                line = " | ".join(
                    part for part in (title, company, str(dates), str(desc)[:500]) if part
                )
                if line:
                    parts.append(line)

    about = resume.get("about") or resume.get("summary") or jobseeker.get("about")
    if about:
        parts.append(f"About: {about}")

    return "\n".join(parts).strip()


def _candidate_name(item: dict[str, Any]) -> str:
    resume = item.get("resume") if isinstance(item.get("resume"), dict) else item
    jobseeker = resume.get("jobseeker") if isinstance(resume.get("jobseeker"), dict) else {}
    for key in ("name", "fullName", "displayName"):
        value = jobseeker.get(key) or resume.get(key) or item.get(key)
        if value:
            return str(value).strip()
    return ""


def _encrypted_jobseeker_id(item: dict[str, Any]) -> str:
    resume = item.get("resume") if isinstance(item.get("resume"), dict) else item
    jobseeker = resume.get("jobseeker") if isinstance(resume.get("jobseeker"), dict) else {}
    for container in (jobseeker, resume, item):
        value = container.get("encryptedJobseekerId") or container.get("jobseekerId")
        if value:
            return str(value).strip()
    return ""


def _is_locked_candidate(item: dict[str, Any]) -> bool:
    if item.get("isUnlocked") is True or item.get("unlocked") is True:
        return False
    unlock_status = str(item.get("unlockStatus") or item.get("status") or "").lower()
    if unlock_status in {"unlocked", "connected", "already_connected"}:
        return False

    resume = item.get("resume") if isinstance(item.get("resume"), dict) else item
    jobseeker = resume.get("jobseeker") if isinstance(resume.get("jobseeker"), dict) else {}
    has_contact = any(
        jobseeker.get(key) or resume.get(key)
        for key in ("email", "phone", "phoneNumber")
    )
    if has_contact:
        return False

    if item.get("isLocked") is True:
        return True
    if item.get("canConnect") is True or item.get("needsUnlock") is True:
        return True
    if _encrypted_jobseeker_id(item) and _candidate_name(item):
        return True
    return False


def _walk_pipeline_candidates(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        name = _candidate_name(node)
        if name and (_encrypted_jobseeker_id(node) or _extract_experience_text(node)):
            out.append(node)
        for value in node.values():
            _walk_pipeline_candidates(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_pipeline_candidates(item, out)


def _dedupe_api_candidates(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in raw:
        if not _is_locked_candidate(item):
            continue
        name = _candidate_name(item)
        enc = _encrypted_jobseeker_id(item)
        key = enc or name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


async def _capture_sourcing_api(page: Page, project: Project) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    async def on_response(response: Response) -> None:
        url = response.url.lower()
        if (
            "rdb2" not in url
            and "candidate" not in url
            and "pipeline" not in url
            and "sourcing" not in url
        ):
            return
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        try:
            body = await response.json()
        except Exception:
            return
        before = len(captured)
        _walk_pipeline_candidates(body, captured)
        if len(captured) > before:
            logger.debug(
                "Captured %s pipeline candidate(s) from %s",
                len(captured) - before,
                url,
            )

    page.on("response", on_response)
    await open_sourcing_project(page, project)
    await page.wait_for_timeout(2500)
    return _dedupe_api_candidates(captured)


async def _extract_profile_from_dom(page: Page) -> tuple[str, str, str]:
    data = await page.evaluate(
        """() => {
            const pickText = (selectors) => {
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (el && el.innerText && el.innerText.trim().length > 2) {
                        return el.innerText.trim();
                    }
                }
                return "";
            };

            const name = pickText([
                "h1",
                "[data-testid*='candidate-name']",
                "[class*='candidate-name']",
                "[class*='profile-name']",
            ]);

            const headline = pickText([
                "[data-testid*='headline']",
                "[class*='headline']",
                "h2",
            ]);

            const main = document.querySelector("main")
                || document.querySelector("[role='main']")
                || document.body;

            let text = (main.innerText || "").trim();
            const contactMarkers = [
                "Connect to unlock",
                "Connect to view",
                "Unlock contact",
            ];
            for (const marker of contactMarkers) {
                const idx = text.indexOf(marker);
                if (idx > 0 && idx < 400) {
                    text = text.slice(idx + marker.length).trim();
                }
            }

            const workIdx = text.search(/Work Experience|Experience|Employment/i);
            if (workIdx >= 0) {
                text = text.slice(workIdx);
            }

            return { name, headline, text: text.slice(0, 12000) };
        }"""
    )
    return (
        str(data.get("name") or "").strip(),
        str(data.get("headline") or "").strip(),
        str(data.get("text") or "").strip(),
    )


async def _current_pipeline_index(page: Page) -> int | None:
    text = await page.inner_text("body")
    match = re.search(r"(\d+)\s+of\s+([\d,]+)", text)
    if not match:
        return None
    return int(match.group(1))


async def _click_next_candidate(page: Page) -> bool:
    selectors = [
        "button[aria-label*='Next' i]",
        "button[title*='Next' i]",
        "[data-testid*='next' i]",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() > 0:
            try:
                await locator.click(timeout=4000)
                await page.wait_for_timeout(1500)
                return True
            except Exception:
                continue

    for label in ("Next", "›", "→"):
        locator = page.get_by_role("button", name=re.compile(re.escape(label), re.I)).first
        if await locator.count() > 0:
            try:
                await locator.click(timeout=4000)
                await page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
    return False


async def _click_previous_candidate(page: Page) -> bool:
    selectors = [
        "button[aria-label*='Previous' i]",
        "button[title*='Previous' i]",
        "[data-testid*='previous' i]",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() > 0:
            try:
                await locator.click(timeout=4000)
                await page.wait_for_timeout(1200)
                return True
            except Exception:
                continue
    return False


async def _go_to_pipeline_index(page: Page, target_index: int) -> None:
    if target_index <= 1:
        return

    current = await _current_pipeline_index(page)
    if current is None:
        for _ in range(target_index - 1):
            if not await _click_next_candidate(page):
                break
        return

    while current > 1:
        if not await _click_previous_candidate(page):
            break
        current = await _current_pipeline_index(page) or current - 1

    current = await _current_pipeline_index(page) or 1
    while current < target_index:
        if not await _click_next_candidate(page):
            break
        current = await _current_pipeline_index(page) or current + 1


async def scrape_locked_candidates(
    page: Page,
    project: Project,
    *,
    limit: int = 25,
) -> list[LockedCandidate]:
    api_items = await _capture_sourcing_api(page, project)
    if api_items:
        candidates: list[LockedCandidate] = []
        for index, item in enumerate(api_items[:limit], start=1):
            name = _candidate_name(item)
            profile_text = _extract_experience_text(item)
            if not profile_text:
                profile_text = name
            jobseeker = (item.get("resume") or {}).get("jobseeker") or {}
            candidates.append(
                LockedCandidate(
                    name=name or f"Candidate {index}",
                    pipeline_index=index,
                    profile_text=profile_text,
                    headline=str(jobseeker.get("headline") or ""),
                    encrypted_jobseeker_id=_encrypted_jobseeker_id(item),
                    metadata={"source": "api"},
                )
            )
        if candidates:
            logger.info(
                "Loaded %s locked candidate(s) from sourcing API for %s",
                len(candidates),
                project.name,
            )
            return candidates

    await open_sourcing_project(page, project)
    await page.wait_for_timeout(2000)

    scraped: list[LockedCandidate] = []
    seen_names: set[str] = set()
    for index in range(1, limit + 1):
        name, headline, profile_text = await _extract_profile_from_dom(page)
        if not name:
            break
        key = name.lower()
        if key in seen_names:
            break
        seen_names.add(key)
        scraped.append(
            LockedCandidate(
                name=name,
                pipeline_index=index,
                profile_text=profile_text or name,
                headline=headline,
                metadata={"source": "dom"},
            )
        )
        if not await _click_next_candidate(page):
            break

    if not scraped:
        raise ZipRecruiterSessionError(
            f"Could not read locked candidates in sourcing for project: {project.name}. "
            "Open the Sourcing tab in ZipRecruiter and confirm candidates are visible."
        )
    logger.info("Scraped %s locked candidate(s) from sourcing DOM for %s", len(scraped), project.name)
    return scraped


async def unlock_candidate_on_page(page: Page, candidate: LockedCandidate) -> bool:
    await _go_to_pipeline_index(page, candidate.pipeline_index)
    await page.wait_for_timeout(1000)

    button_patterns = (
        re.compile(r"^Connect$", re.I),
        re.compile(r"Connect to unlock", re.I),
        re.compile(r"Unlock", re.I),
    )
    for pattern in button_patterns:
        locator = page.get_by_role("button", name=pattern).first
        if await locator.count() == 0:
            locator = page.get_by_text(pattern).first
        if await locator.count() == 0:
            continue
        try:
            await locator.click(timeout=5000)
            await page.wait_for_timeout(2500)
            candidate.is_unlocked = True
            return True
        except Exception as error:
            logger.warning("Unlock click failed for %s: %s", candidate.name, error)

    raise ZipRecruiterSessionError(
        f"Could not find Connect/Unlock for {candidate.name} in {page.url}"
    )


async def unlock_candidates(
    page: Page,
    project: Project,
    candidates: list[LockedCandidate],
) -> list[LockedCandidate]:
    await open_sourcing_project(page, project)
    unlocked: list[LockedCandidate] = []
    for candidate in candidates:
        try:
            await unlock_candidate_on_page(page, candidate)
            unlocked.append(candidate)
        except ZipRecruiterSessionError as error:
            logger.warning("%s", error)
    return unlocked


async def run_with_browser(coro):
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        return await coro(page)
