from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Page, Response

from zr.browser import ZipRecruiterSessionError, ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_BASE_URL, ZIPRECRUITER_RDB_URL
from zr.rdb_api import project_pipeline_url

UNLOCK_COUNT_KEYS = (
    "unlocked_count",
    "unlockedCount",
    "num_unlocked",
    "unlocked_candidates",
    "unlock_count",
    "unlocked_resumes",
    "unlocked_resume_count",
    "total_unlocked",
    "candidates_unlocked",
    "resume_count",
    "candidate_count",
)

CAPTURE_URL_RE = re.compile(
    r"project|resume-database|resume_database|rdb|unlocked|candidate|jobseeker",
    re.I,
)
IGNORE_KEY_RE = re.compile(r"preference|modal|analytics|tracking|sentry", re.I)
PROJECT_URL_RE = re.compile(r"/project[s]?/|project_id=|/rdb/project", re.I)

NOISE_NAME_EXACT = {
    "projects",
    "project",
    "settings",
    "help",
    "unlocked",
    "browse database",
    "resume database",
    "my unlocked resumes",
    "create project",
    "search",
    "filters",
    "candidates",
    "candidate",
    "owner",
    "location",
    "actions",
    "alerts",
    "email alerts",
    "project settings",
}

NOISE_NAME_SUBSTRINGS = (
    "sign in",
    "log out",
    "logout",
    "cookie",
    "privacy",
    "terms of",
    "ziprecruiter",
    "years of experience",
    "unlock contact",
    "verify you are human",
    "performing security",
)


def _looks_like_project_url(url: str) -> bool:
    if not url:
        return False
    return bool(PROJECT_URL_RE.search(url))


def _is_valid_project_name(name: str) -> bool:
    cleaned = " ".join(name.split())
    if len(cleaned) < 4 or len(cleaned) > 120:
        return False

    lowered = cleaned.lower()
    if lowered in NOISE_NAME_EXACT:
        return False
    if any(term in lowered for term in NOISE_NAME_SUBSTRINGS):
        return False
    if lowered.isdigit():
        return False
    if "@" in cleaned and " " not in cleaned:
        return False
    if cleaned.count("\n") > 0:
        return False

    return True


def _is_authoritative_project(project: Project) -> bool:
    if project.project_id:
        return True
    if _looks_like_project_url(project.url):
        return True
    return False


def _filter_projects(projects: list[Project], *, authoritative_only: bool = False) -> list[Project]:
    filtered: list[Project] = []
    for project in projects:
        if not _is_valid_project_name(project.name):
            continue
        if authoritative_only and not _is_authoritative_project(project):
            continue
        filtered.append(project)
    return _dedupe_projects(filtered)


UNLOCKED_IN_TEXT_RE = re.compile(
    r"(\d+)\s+unlocked|unlocked[^\d]{0,20}(\d+)|(\d+)\s+candidates?\s+unlocked|"
    r"(\d+)\s+resumes?\s+unlocked",
    re.I,
)


@dataclass
class Project:
    name: str
    owner: str = ""
    location: str = ""
    job_title: str = ""
    project_id: str = ""
    url: str = ""
    unlocked_count: int | None = None

    def display_line(self, index: int) -> str:
        count = self.unlocked_count if self.unlocked_count is not None else "?"
        return f"{index}. *{self.name}* — *{count}* unlocked"


@dataclass
class ProjectFetchResult:
    projects: list[Project] = field(default_factory=list)
    account_hint: str = ""
    page_url: str = ""

    @property
    def total_unlocked(self) -> int:
        return sum(
            project.unlocked_count
            for project in self.projects
            if project.unlocked_count is not None
        )

    @property
    def has_any_counts(self) -> bool:
        return any(project.unlocked_count is not None for project in self.projects)


def _parse_unlock_count_from_text(text: str) -> int | None:
    match = UNLOCKED_IN_TEXT_RE.search(text)
    if not match:
        return None
    for group in match.groups():
        if group and str(group).isdigit():
            return int(group)
    return None


def _extract_unlocked_count(item: dict[str, Any]) -> int | None:
    for key in UNLOCK_COUNT_KEYS:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

    for key, value in item.items():
        if "unlock" not in str(key).lower():
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

    nested = item.get("stats") or item.get("metrics") or item.get("counts") or item.get("summary")
    if isinstance(nested, dict):
        return _extract_unlocked_count(nested)

    return None


def _project_name_from_item(item: dict[str, Any]) -> str:
    for key in ("name", "title", "project_name", "label"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _project_id_from_item(item: dict[str, Any]) -> str:
    for key in ("project_id", "projectId", "id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _merge_project(existing: Project, incoming: Project) -> Project:
    return Project(
        name=existing.name or incoming.name,
        owner=existing.owner or incoming.owner,
        location=existing.location or incoming.location,
        job_title=existing.job_title or incoming.job_title,
        project_id=existing.project_id or incoming.project_id,
        url=existing.url or incoming.url,
        unlocked_count=(
            incoming.unlocked_count
            if incoming.unlocked_count is not None
            else existing.unlocked_count
        ),
    )


def _project_from_item(item: dict[str, Any]) -> Project | None:
    name = _project_name_from_item(item)
    if not name:
        return None

    return Project(
        name=name,
        owner=str(item.get("owner") or item.get("owner_name") or item.get("created_by") or ""),
        location=str(item.get("location") or item.get("city") or ""),
        job_title=str(item.get("job_title") or item.get("role") or ""),
        project_id=_project_id_from_item(item),
        url=str(item.get("url") or item.get("href") or ""),
        unlocked_count=_extract_unlocked_count(item),
    )


def _walk_json_for_projects(node: Any, matches: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        name = _project_name_from_item(node)
        project_id = _project_id_from_item(node)
        has_explicit_project_field = any(
            key in node for key in ("project_id", "projectId", "project_name", "projectName")
        )

        if name and (project_id or has_explicit_project_field):
            matches.append(node)

        for value in node.values():
            _walk_json_for_projects(value, matches)
    elif isinstance(node, list):
        for item in node:
            _walk_json_for_projects(item, matches)


def _walk_json_for_candidate_counts(
    node: Any,
    counts_by_id: dict[str, int],
    counts_by_name: dict[str, int],
) -> None:
    if isinstance(node, dict):
        project_id = str(node.get("project_id") or node.get("projectId") or "").strip()
        project_name = str(
            node.get("project_name") or node.get("projectName") or node.get("name") or ""
        ).strip()

        looks_like_candidate = any(
            key in node
            for key in (
                "candidate_id",
                "candidateId",
                "jobseeker_id",
                "resume_url",
                "resumeUrl",
                "unlocked",
                "was_unlocked",
            )
        )

        if looks_like_candidate and (project_id or project_name):
            if project_id:
                counts_by_id[project_id] = counts_by_id.get(project_id, 0) + 1
            if project_name:
                lowered = project_name.lower()
                counts_by_name[lowered] = counts_by_name.get(lowered, 0) + 1

        for value in node.values():
            _walk_json_for_candidate_counts(value, counts_by_id, counts_by_name)
    elif isinstance(node, list):
        for item in node:
            _walk_json_for_candidate_counts(item, counts_by_id, counts_by_name)


def _projects_from_payload(payload: Any) -> list[Project]:
    matches: list[dict[str, Any]] = []
    _walk_json_for_projects(payload, matches)

    by_key: dict[str, Project] = {}
    for item in matches:
        project = _project_from_item(item)
        if not project or not _is_valid_project_name(project.name):
            continue
        key = project.project_id or project.name.lower()
        by_key[key] = _merge_project(by_key.get(key, project), project)

    return list(by_key.values())


def _candidate_counts_from_payload(payload: Any) -> tuple[dict[str, int], dict[str, int]]:
    counts_by_id: dict[str, int] = {}
    counts_by_name: dict[str, int] = {}
    _walk_json_for_candidate_counts(payload, counts_by_id, counts_by_name)
    return counts_by_id, counts_by_name


def _dedupe_projects(projects: list[Project]) -> list[Project]:
    by_key: dict[str, Project] = {}
    for project in projects:
        key = project.project_id or project.name.lower()
        by_key[key] = _merge_project(by_key.get(key, project), project)
    return list(by_key.values())


async def _collect_from_network(page: Page, navigate: bool = True) -> tuple[list[Project], dict[str, int], dict[str, int]]:
    projects: list[Project] = []
    counts_by_id: dict[str, int] = {}
    counts_by_name: dict[str, int] = {}

    async def handle_response(response: Response) -> None:
        url = response.url
        if IGNORE_KEY_RE.search(url):
            return
        if not CAPTURE_URL_RE.search(url):
            return
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return
        try:
            payload = await response.json()
        except Exception:
            return

        projects.extend(_projects_from_payload(payload))
        by_id, by_name = _candidate_counts_from_payload(payload)
        for key, value in by_id.items():
            counts_by_id[key] = counts_by_id.get(key, 0) + value
        for key, value in by_name.items():
            counts_by_name[key] = counts_by_name.get(key, 0) + value

    page.on("response", handle_response)
    if navigate:
        await page.goto(ZIPRECRUITER_RDB_URL, wait_until="networkidle")
        await page.wait_for_timeout(2500)
    page.remove_listener("response", handle_response)

    return _dedupe_projects(projects), counts_by_id, counts_by_name


async def _projects_from_dom(page: Page) -> list[Project]:
    raw_projects = await page.evaluate(
        """() => {
            const skip = [
                "create project",
                "browse database",
                "my unlocked",
                "settings",
                "help",
                "resume database",
                "projects",
                "owner",
                "location",
                "actions",
            ];

            const results = [];
            const seen = new Set();

            function addProject(name, href, unlockedCount) {
                const cleaned = (name || "").trim();
                const lowered = cleaned.toLowerCase();
                if (!cleaned || cleaned.length < 4 || cleaned.length > 120) return;
                if (skip.some((term) => lowered === term || lowered.startsWith(term + "\\n"))) return;
                if (seen.has(lowered)) return;
                seen.add(lowered);
                results.push({ name: cleaned, href: href || "", unlockedCount });
            }

            function parseRow(text, href) {
                const lines = text.split("\\n").map((line) => line.trim()).filter(Boolean);
                if (!lines.length) return;

                let unlockedCount = null;
                const unlockMatch = text.match(
                    /(\\d+)\\s+unlocked|unlocked[^\\d]{0,20}(\\d+)|(\\d+)\\s+candidates?\\s+unlocked|(\\d+)\\s+resumes?\\s+unlocked/i
                );
                if (unlockMatch) {
                    unlockedCount = Number(
                        unlockMatch[1] || unlockMatch[2] || unlockMatch[3] || unlockMatch[4]
                    );
                }

                for (const line of lines) {
                    if (/^\\d+$/.test(line) && unlockedCount === null) {
                        unlockedCount = Number(line);
                    }
                }

                addProject(lines[0], href, unlockedCount);
            }

            // Best signal: project links
            document.querySelectorAll("a[href*='/emp/rdb/project/'], a[href*='project']").forEach((link) => {
                const href = link.getAttribute("href") || "";
                if (!/emp\\/rdb\\/project|\\/project/i.test(href)) return;
                const row = link.closest("tr") || link.closest("article") || link.closest("li") || link;
                parseRow(row.innerText || link.innerText || "", href);
            });

            // Projects dashboard table rows
            document.querySelectorAll("table tbody tr").forEach((row) => {
                const header = row.closest("table")?.innerText?.toLowerCase() || "";
                if (!header.includes("project")) return;
                const link = row.querySelector("a[href]");
                parseRow(row.innerText || "", link ? link.getAttribute("href") : "");
            });

            return results;
        }"""
    )

    projects = [
        Project(
            name=item["name"],
            url=item.get("href") or "",
            unlocked_count=item.get("unlockedCount"),
        )
        for item in raw_projects
        if _is_valid_project_name(item["name"])
    ]
    return _filter_projects(projects)


async def _try_open_unlocked_tab(page: Page) -> None:
    tab_selectors = [
        "text=My Unlocked Resumes",
        "text=Unlocked Resumes",
        "[role='tab']:has-text('Unlocked')",
        "button:has-text('Unlocked')",
        "a:has-text('Unlocked')",
    ]
    for selector in tab_selectors:
        try:
            tab = page.locator(selector).first
            if await tab.count() > 0:
                await tab.click(timeout=3000)
                await page.wait_for_timeout(2000)
                return
        except Exception:
            continue


async def enrich_projects_with_urls(page: Page, projects: list[Project]) -> list[Project]:
    await page.goto(ZIPRECRUITER_RDB_URL, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(1500)
    dom_projects = await _projects_from_dom(page)
    dom_by_name = {item.name.lower(): item for item in dom_projects}

    enriched: list[Project] = []
    for project in projects:
        dom_match = dom_by_name.get(project.name.lower())
        enriched.append(_merge_project(project, dom_match or Project(name=project.name)))
    return enriched


async def open_project(page: Page, project: Project) -> None:
    if not project.project_id:
        raise ZipRecruiterSessionError(f"Could not open project: {project.name}")

    target = project_pipeline_url(project.project_id)
    response = await page.goto(target, wait_until="networkidle", timeout=60000)
    if not response or response.status >= 400 or project.project_id not in page.url:
        raise ZipRecruiterSessionError(f"Could not open project: {project.name}")


def _apply_count_maps(
    projects: list[Project],
    counts_by_id: dict[str, int],
    counts_by_name: dict[str, int],
) -> list[Project]:
    updated: list[Project] = []
    for project in projects:
        count = project.unlocked_count
        if count is None and project.project_id:
            count = counts_by_id.get(project.project_id)
        if count is None:
            count = counts_by_name.get(project.name.lower())
        updated.append(_merge_project(project, Project(name=project.name, unlocked_count=count)))
    return updated


async def _count_candidates_on_page(page: Page) -> int | None:
    body_text = await page.inner_text("body")
    text_count = _parse_unlock_count_from_text(body_text)
    if text_count is not None:
        return text_count

    dom_count = await page.evaluate(
        """() => {
            const selectors = [
                "[data-testid*='candidate']",
                "[class*='candidate']",
                "[data-testid*='resume']",
                "[class*='resume-card']",
                "article",
            ];
            let maxCount = 0;
            for (const selector of selectors) {
                const count = document.querySelectorAll(selector).length;
                if (count > maxCount) maxCount = count;
            }
            return maxCount;
        }"""
    )
    return dom_count if dom_count and dom_count > 0 else None


async def _fill_missing_counts(page: Page, projects: list[Project]) -> list[Project]:
    if all(project.unlocked_count is not None for project in projects):
        return projects

    list_url = page.url
    updated: list[Project] = []

    for project in projects:
        if project.unlocked_count is not None:
            updated.append(project)
            continue

        count: int | None = None

        try:
            if project.url:
                target = urljoin(ZIPRECRUITER_BASE_URL, project.url)
                await page.goto(target, wait_until="networkidle", timeout=45000)
            else:
                await open_project(page, project)

            await _try_open_unlocked_tab(page)
            count = await _count_candidates_on_page(page)
        except Exception:
            count = None

        updated.append(_merge_project(project, Project(name=project.name, unlocked_count=count)))

    try:
        await page.goto(list_url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        pass

    return updated


async def _account_hint(page: Page) -> str:
    selectors = ["[data-testid*='user']", "[class*='account']", "[class*='profile']", "header"]
    for selector in selectors:
        element = await page.query_selector(selector)
        if not element:
            continue
        text = (await element.inner_text()).strip()
        if "@" in text:
            for token in text.split():
                if "@" in token:
                    return token.strip()
    return ""


def _merge_counts_from_dom(projects: list[Project], dom_projects: list[Project]) -> list[Project]:
    dom_by_name = {item.name.lower(): item for item in dom_projects}
    merged: list[Project] = []

    for project in projects:
        dom_match = dom_by_name.get(project.name.lower())
        if dom_match and dom_match.unlocked_count is not None:
            merged.append(_merge_project(project, dom_match))
        else:
            merged.append(project)

    return merged


async def fetch_projects_on_page(page: Page) -> ProjectFetchResult:
    projects, counts_by_id, counts_by_name = await _collect_from_network(page, navigate=True)
    projects = _filter_projects(projects)

    dom_projects = await _projects_from_dom(page)

    if not projects:
        projects = dom_projects
    else:
        projects = _merge_counts_from_dom(projects, dom_projects)

    await _try_open_unlocked_tab(page)
    extra_projects, extra_by_id, extra_by_name = await _collect_from_network(page, navigate=False)

    extra_projects = _filter_projects(extra_projects)
    if projects:
        projects = _merge_counts_from_dom(projects, extra_projects)
    elif extra_projects:
        projects = extra_projects

    counts_by_id.update(extra_by_id)
    counts_by_name.update(extra_by_name)
    projects = _apply_count_maps(projects, counts_by_id, counts_by_name)
    projects = _filter_projects(projects)

    if not projects:
        raise ZipRecruiterSessionError(
            "Logged in, but no projects were found. "
            f"Current URL: {page.url}."
        )

    if not all(project.unlocked_count is not None for project in projects):
        projects = await _fill_missing_counts(page, projects)

    projects = _filter_projects(projects)
    projects.sort(key=lambda item: item.name.lower())

    return ProjectFetchResult(
        projects=projects,
        account_hint=await _account_hint(page),
        page_url=page.url,
    )


async def fetch_projects() -> ProjectFetchResult:
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        return await fetch_projects_on_page(page)


def format_projects_for_slack(result: ProjectFetchResult) -> str:
    lines = ["*Unlocked candidate counts by project*\n"]

    for index, project in enumerate(result.projects, start=1):
        lines.append(project.display_line(index))

    if result.has_any_counts:
        lines.append(f"\n*Total:* {result.total_unlocked} unlocked candidates")
    else:
        lines.append(
            "\n_Could not read counts from ZipRecruiter. "
            "Try opening Resume Database manually and share a screenshot of the projects table._"
        )

    return "\n".join(lines)
