from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Page, Response

from zr.projects import Project, _try_open_unlocked_tab, open_project

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{8,}\d)")

CAPTURE_CANDIDATE_URL_RE = re.compile(
    r"candidate|jobseeker|unlocked|resume|profile",
    re.I,
)
IGNORE_URL_RE = re.compile(r"preference|modal|analytics|tracking|sentry", re.I)


@dataclass
class Candidate:
    name: str
    email: str = ""
    phone: str = ""
    project_name: str = ""
    project_id: str = ""
    candidate_id: str = ""
    resume_url: str = ""
    resume_filename: str = ""
    exported_at: str = ""

    def dedupe_key(self) -> str:
        if self.candidate_id:
            return f"id:{self.candidate_id}"
        if self.email:
            return f"email:{self.email.lower()}"
        return f"name:{self.name.lower()}:{self.project_name.lower()}"


@dataclass
class CandidateCollection:
    candidates: list[Candidate] = field(default_factory=list)

    def add(self, candidate: Candidate) -> None:
        if not candidate.name.strip():
            return
        key = candidate.dedupe_key()
        for existing in self.candidates:
            if existing.dedupe_key() == key:
                if not existing.email and candidate.email:
                    existing.email = candidate.email
                if not existing.phone and candidate.phone:
                    existing.phone = candidate.phone
                if not existing.resume_url and candidate.resume_url:
                    existing.resume_url = candidate.resume_url
                if not existing.candidate_id and candidate.candidate_id:
                    existing.candidate_id = candidate.candidate_id
                return
        self.candidates.append(candidate)


def _extract_contact_fields(item: dict[str, Any]) -> tuple[str, str, str, str]:
    name = (
        item.get("name")
        or " ".join(
            part
            for part in [
                item.get("first_name"),
                item.get("last_name"),
            ]
            if part
        ).strip()
        or item.get("full_name")
        or ""
    )
    email = str(item.get("email") or item.get("email_address") or "")
    phone = str(
        item.get("phone")
        or item.get("mobile")
        or item.get("phone_number")
        or item.get("contact_phone")
        or ""
    )
    candidate_id = str(item.get("candidate_id") or item.get("candidateId") or item.get("id") or "")
    return str(name).strip(), email.strip(), phone.strip(), candidate_id.strip()


def _extract_resume_url(item: dict[str, Any]) -> str:
    for key in (
        "resume_url",
        "resumeUrl",
        "download_url",
        "downloadUrl",
        "pdf_url",
        "file_url",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    resume = item.get("resume")
    if isinstance(resume, dict):
        url = resume.get("url") or resume.get("download_url")
        if isinstance(url, str):
            return url.strip()
    return ""


def _looks_like_candidate(item: dict[str, Any]) -> bool:
    name, email, phone, candidate_id = _extract_contact_fields(item)
    if not name:
        return False
    return bool(email or phone or candidate_id or _extract_resume_url(item))


def _walk_json_for_candidates(
    node: Any,
    project: Project,
    collection: CandidateCollection,
) -> None:
    if isinstance(node, dict):
        if _looks_like_candidate(node):
            name, email, phone, candidate_id = _extract_contact_fields(node)
            collection.add(
                Candidate(
                    name=name,
                    email=email,
                    phone=phone,
                    project_name=project.name,
                    project_id=project.project_id,
                    candidate_id=candidate_id,
                    resume_url=_extract_resume_url(node),
                )
            )
        for value in node.values():
            _walk_json_for_candidates(value, project, collection)
    elif isinstance(node, list):
        for item in node:
            _walk_json_for_candidates(item, project, collection)


async def _collect_from_network(page: Page, project: Project) -> CandidateCollection:
    collection = CandidateCollection()

    async def handle_response(response: Response) -> None:
        url = response.url
        if IGNORE_URL_RE.search(url):
            return
        if not CAPTURE_CANDIDATE_URL_RE.search(url):
            return
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        _walk_json_for_candidates(payload, project, collection)

    page.on("response", handle_response)
    await page.wait_for_timeout(2500)
    page.remove_listener("response", handle_response)
    return collection


async def _collect_from_dom(page: Page, project: Project) -> CandidateCollection:
    collection = CandidateCollection()
    raw = await page.evaluate(
        """() => {
            const results = [];
            const seen = new Set();
            const nodes = document.querySelectorAll(
                "[data-testid*='candidate'], [class*='candidate'], article, li, tr, [class*='resume']"
            );

            for (const node of nodes) {
                const text = (node.innerText || "").trim();
                if (!text || text.length < 8 || text.length > 500) continue;

                const lines = text.split("\\n").map((line) => line.trim()).filter(Boolean);
                if (!lines.length) continue;

                const emailMatch = text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/);
                const phoneMatch = text.match(/(\\+?\\d[\\d\\s().-]{8,}\\d)/);
                if (!emailMatch && !phoneMatch) continue;

                const name = lines[0];
                const key = (name + "|" + (emailMatch ? emailMatch[0] : "")).toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);

                const link = node.querySelector("a[href*='resume'], a[href*='download'], a[download]");
                results.push({
                    name,
                    email: emailMatch ? emailMatch[0] : "",
                    phone: phoneMatch ? phoneMatch[1] : "",
                    resumeUrl: link ? link.getAttribute("href") : "",
                });
            }
            return results;
        }"""
    )

    for item in raw:
        collection.add(
            Candidate(
                name=item["name"],
                email=item.get("email") or "",
                phone=item.get("phone") or "",
                project_name=project.name,
                project_id=project.project_id,
                resume_url=item.get("resumeUrl") or "",
            )
        )

    return collection


async def collect_candidates_for_project(page: Page, project: Project) -> list[Candidate]:
    await open_project(page, project)
    await _try_open_unlocked_tab(page)

    network = await _collect_from_network(page, project)
    dom = await _collect_from_dom(page, project)

    merged = CandidateCollection()
    exported_at = datetime.now(timezone.utc).isoformat()
    for candidate in network.candidates + dom.candidates:
        candidate.exported_at = exported_at
        merged.add(candidate)

    return merged.candidates
