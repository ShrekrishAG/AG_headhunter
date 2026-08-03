"""Browse locked pipeline candidates, read profiles, and unlock via Connect."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page, Response

from zr.browser import ZipRecruiterSessionError, ensure_logged_in, ziprecruiter_context
from zr.projects import Project
from zr.rdb_api import (
    SOURCING_PAGE_SIZE,
    fetch_sourcing_jobseekers,
    open_sourcing_project,
    project_sourcing_url,
)

logger = logging.getLogger(__name__)

EXPERIENCE_KEYS = (
    "workHistory",
    "employmentHistory",
    "employment",
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
        location = location.get("name") or ", ".join(
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
                organization = pos.get("organization")
                company = (
                    pos.get("company")
                    or pos.get("employer")
                    or pos.get("companyName")
                    or (
                        organization.get("name")
                        if isinstance(organization, dict)
                        else ""
                    )
                    or ""
                )
                desc = pos.get("description") or pos.get("summary") or ""
                dates = pos.get("dateRange") or pos.get("dates") or ""
                if isinstance(dates, dict):
                    dates = " - ".join(
                        _format_partial_date(dates.get(key))
                        for key in ("start", "end")
                        if dates.get(key)
                    )
                line = " | ".join(
                    part for part in (title, company, str(dates), str(desc)[:500]) if part
                )
                if line:
                    parts.append(line)

    skills = item.get("skills") or resume.get("skills") or jobseeker.get("skills")
    if isinstance(skills, list) and skills:
        skill_names = [
            str(skill.get("name") if isinstance(skill, dict) else skill).strip()
            for skill in skills[:20]
        ]
        skill_names = [name for name in skill_names if name]
        if skill_names:
            parts.append("Skills: " + ", ".join(skill_names))

    about = resume.get("about") or resume.get("summary") or jobseeker.get("about")
    if about:
        parts.append(f"About: {about}")

    return "\n".join(parts).strip()


def _format_partial_date(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "").strip()
    year = value.get("year")
    month = value.get("month")
    if year and month:
        return f"{month}/{year}"
    if year:
        return str(year)
    return ""


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
    for match in re.finditer(r"(\d+)\s+of\s+([\d,]+)(?:\s+(\w+))?", text):
        trailing = (match.group(3) or "").lower()
        # Skip credit counters like "250 of 250 left"
        if trailing == "left":
            continue
        return int(match.group(1))
    return None


async def _click_next_candidate(page: Page) -> bool:
    selectors = [
        "button[aria-label='Next candidate']",
        "button[aria-label*='Next candidate' i]",
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

    for label in ("Next candidate", "Next", "›", "→"):
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
        "button[aria-label='Previous candidate']",
        "button[aria-label*='Previous candidate' i]",
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


async def _go_to_sourcing_result_page(page: Page, page_number: int) -> None:
    if page_number <= 1:
        # Prefer returning to page 1 when needed
        page_one = page.get_by_role("button", name="1", exact=True)
        if await page_one.count() > 0:
            try:
                await page_one.first.click(timeout=3000)
                await page.wait_for_timeout(1500)
            except Exception:
                pass
        return

    button = page.get_by_role("button", name=str(page_number), exact=True)
    if await button.count() == 0:
        button = page.get_by_text(str(page_number), exact=True)
    if await button.count() == 0:
        logger.warning("Could not find sourcing page button %s", page_number)
        return
    try:
        await button.first.click(timeout=4000)
        await page.wait_for_timeout(2000)
    except Exception as error:
        logger.warning("Failed to open sourcing page %s: %s", page_number, error)


async def _select_candidate_in_list(page: Page, candidate: LockedCandidate) -> bool:
    if not candidate.name:
        return False
    locator = page.get_by_text(candidate.name, exact=True)
    if await locator.count() == 0:
        return False
    try:
        await locator.first.click(timeout=5000)
        await page.wait_for_timeout(1200)
        return True
    except Exception as error:
        logger.warning("Could not select candidate %s: %s", candidate.name, error)
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


def _api_item_to_candidate(item: dict[str, Any], index: int) -> LockedCandidate:
    name = _candidate_name(item)
    profile_text = _extract_experience_text(item)
    if not profile_text:
        profile_text = name
    jobseeker = (item.get("resume") or {}).get("jobseeker") or {}
    location = item.get("location") or jobseeker.get("location") or ""
    if isinstance(location, dict):
        location = (
            location.get("name")
            or ", ".join(
                str(location.get(key) or "")
                for key in ("city", "state", "country")
                if location.get(key)
            )
        )
    headline = str(
        jobseeker.get("headline")
        or item.get("headline")
        or (
            f"{item.get('yearsOfExperience')} years experience"
            if item.get("yearsOfExperience")
            else ""
        )
    )
    return LockedCandidate(
        name=name or f"Candidate {index}",
        pipeline_index=index,
        profile_text=profile_text,
        headline=headline,
        location=str(location or ""),
        encrypted_jobseeker_id=_encrypted_jobseeker_id(item),
        metadata={"source": "api"},
    )


async def scrape_locked_candidates(
    page: Page,
    project: Project,
    *,
    limit: int = 25,
) -> list[LockedCandidate]:
    project_id = project.project_id or ""
    if project_id:
        await open_sourcing_project(page, project)
        try:
            api_items = await fetch_sourcing_jobseekers(page, project_id, limit=limit)
        except Exception as error:
            logger.warning(
                "SearchAPI pagination failed for %s (%s); falling back to page capture",
                project.name,
                error,
            )
            api_items = []
        if api_items:
            candidates = [
                _api_item_to_candidate(item, index)
                for index, item in enumerate(api_items[:limit], start=1)
            ]
            # Search results are locked prospects; keep ones with a usable identity
            candidates = [
                candidate
                for candidate in candidates
                if candidate.name and (candidate.encrypted_jobseeker_id or candidate.profile_text)
            ]
            if candidates:
                logger.info(
                    "Loaded %s locked candidate(s) from SearchAPI for %s (requested %s)",
                    len(candidates),
                    project.name,
                    limit,
                )
                return candidates

    api_items = await _capture_sourcing_api(page, project)
    if api_items:
        candidates = [
            _api_item_to_candidate(item, index)
            for index, item in enumerate(api_items[:limit], start=1)
        ]
        if candidates:
            logger.info(
                "Loaded %s locked candidate(s) from sourcing API capture for %s",
                len(candidates),
                project.name,
            )
            if len(candidates) < limit:
                logger.warning(
                    "Sourcing capture only returned %s/%s for %s "
                    "(ZipRecruiter first-page limit; SearchAPI pagination preferred)",
                    len(candidates),
                    limit,
                    project.name,
                )
            return candidates

    await open_sourcing_project(page, project)
    await page.wait_for_timeout(2000)

    scraped: list[LockedCandidate] = []
    seen_names: set[str] = set()
    for index in range(1, limit + 1):
        page_number = (index - 1) // SOURCING_PAGE_SIZE + 1
        if index == 1 or (index - 1) % SOURCING_PAGE_SIZE == 0:
            await _go_to_sourcing_result_page(page, page_number)
        name, headline, profile_text = await _extract_profile_from_dom(page)
        if not name:
            break
        key = name.lower()
        if key in seen_names:
            if not await _click_next_candidate(page):
                break
            continue
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


async def _open_candidate_detail(
    page: Page,
    project: Project,
    candidate: LockedCandidate,
) -> None:
    """Open the candidate profile modal (Connect lives inside ReactModalPortal)."""
    project_id = project.project_id or ""
    if project_id and candidate.encrypted_jobseeker_id:
        target = (
            f"{project_sourcing_url(project_id)}"
            f"?encryptedJobseekerId={candidate.encrypted_jobseeker_id}"
        )
        await page.goto(target, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        modal_connect = page.locator(".ReactModalPortal").get_by_role(
            "button", name=re.compile(r"^Connect$", re.I)
        )
        if await modal_connect.count() > 0:
            return

    page_number = max(1, (candidate.pipeline_index - 1) // SOURCING_PAGE_SIZE + 1)
    await _go_to_sourcing_result_page(page, page_number)
    selected = await _select_candidate_in_list(page, candidate)
    if not selected:
        await _go_to_pipeline_index(page, candidate.pipeline_index)
    await page.wait_for_timeout(1000)


async def _click_connect_button(page: Page, candidate: LockedCandidate) -> bool:
    """Click Connect in the profile modal — not the list-row Connect behind it."""
    patterns = (
        re.compile(r"^Connect$", re.I),
        re.compile(r"Connect to unlock", re.I),
        re.compile(r"^Unlock$", re.I),
    )

    for pattern in patterns:
        modal = page.locator(".ReactModalPortal").filter(
            has=page.get_by_role("button", name=pattern)
        )
        if await modal.count() > 0:
            button = modal.last.get_by_role("button", name=pattern).first
            try:
                await button.click(timeout=8000)
                await page.wait_for_timeout(2500)
                await _confirm_unlock_dialog(page)
                return True
            except Exception as error:
                logger.warning(
                    "Modal unlock click failed for %s: %s — trying force click",
                    candidate.name,
                    error,
                )
                try:
                    await button.click(timeout=5000, force=True)
                    await page.wait_for_timeout(2500)
                    await _confirm_unlock_dialog(page)
                    return True
                except Exception as force_error:
                    logger.warning(
                        "Force modal unlock failed for %s: %s",
                        candidate.name,
                        force_error,
                    )

        # Fallback: JS click on visible Connect inside any open portal
        clicked = await page.evaluate(
            """(patternSource) => {
                const re = new RegExp(patternSource, 'i');
                const portals = [...document.querySelectorAll('.ReactModalPortal')];
                for (const portal of portals.reverse()) {
                    const buttons = [...portal.querySelectorAll('button')];
                    for (const button of buttons) {
                        const label = (button.innerText || '').trim();
                        if (!re.test(label)) continue;
                        const rect = button.getBoundingClientRect();
                        if (rect.width < 2 || rect.height < 2) continue;
                        button.click();
                        return true;
                    }
                }
                return false;
            }""",
            pattern.pattern,
        )
        if clicked:
            await page.wait_for_timeout(2500)
            await _confirm_unlock_dialog(page)
            return True

    return False


async def _confirm_unlock_dialog(page: Page) -> None:
    """Dismiss/confirm any post-Connect confirmation dialog if present."""
    for label in (
        re.compile(r"^Confirm$", re.I),
        re.compile(r"^Yes[, ]?connect", re.I),
        re.compile(r"^Connect anyway$", re.I),
        re.compile(r"^Continue$", re.I),
        re.compile(r"^OK$", re.I),
    ):
        button = page.get_by_role("button", name=label).first
        if await button.count() == 0:
            continue
        try:
            await button.click(timeout=2500)
            await page.wait_for_timeout(1500)
            return
        except Exception:
            continue


async def _candidate_appears_unlocked(page: Page, candidate: LockedCandidate) -> bool:
    """Best-effort check that Connect succeeded (contact visible / Connect gone)."""
    modal = page.locator(".ReactModalPortal").last
    text = ""
    try:
        text = await modal.inner_text(timeout=2000)
    except Exception:
        try:
            text = await page.inner_text("body")
        except Exception:
            return False

    lowered = text.lower()
    if "hide this candidate" in lowered and re.search(
        r"\bconnect\b", text, re.I
    ):
        # Still showing Connect in modal → likely not unlocked yet
        connect_in_modal = page.locator(".ReactModalPortal").get_by_role(
            "button", name=re.compile(r"^Connect$", re.I)
        )
        if await connect_in_modal.count() > 0:
            return False

    if re.search(r"[\w.+-]+@[\w.-]+\.\w+", text):
        return True
    if re.search(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text):
        return True
    if re.search(r"message|email|phone|contact", lowered) and not re.search(
        r"^connect$", text, re.I | re.M
    ):
        connect_in_modal = page.locator(".ReactModalPortal").get_by_role(
            "button", name=re.compile(r"^Connect$", re.I)
        )
        return await connect_in_modal.count() == 0

    connect_in_modal = page.locator(".ReactModalPortal").get_by_role(
        "button", name=re.compile(r"^Connect$", re.I)
    )
    return await connect_in_modal.count() == 0


async def unlock_candidate_on_page(
    page: Page,
    project: Project,
    candidate: LockedCandidate,
) -> bool:
    await _open_candidate_detail(page, project, candidate)

    if not await _click_connect_button(page, candidate):
        raise ZipRecruiterSessionError(
            f"Could not find Connect/Unlock for {candidate.name} in {page.url}"
        )

    unlocked = await _candidate_appears_unlocked(page, candidate)
    if unlocked:
        candidate.is_unlocked = True
        logger.info("Unlocked %s in %s", candidate.name, project.name)
        return True

    # Connect click may have worked even if UI is slow to refresh contact fields
    candidate.is_unlocked = True
    logger.info(
        "Clicked Connect for %s in %s (contact fields not yet confirmed)",
        candidate.name,
        project.name,
    )
    return True


async def unlock_candidates(
    page: Page,
    project: Project,
    candidates: list[LockedCandidate],
) -> list[LockedCandidate]:
    await open_sourcing_project(page, project)
    unlocked: list[LockedCandidate] = []
    for candidate in candidates:
        try:
            await unlock_candidate_on_page(page, project, candidate)
            unlocked.append(candidate)
        except ZipRecruiterSessionError as error:
            logger.warning("%s", error)
        except Exception as error:
            logger.warning("Unlock failed for %s: %s", candidate.name, error)
    return unlocked


async def run_with_browser(coro):
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        return await coro(page)
