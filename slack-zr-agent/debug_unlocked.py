"""Probe unlocked candidate pages for a project."""

import asyncio

from zr.browser import ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_BASE_URL
from zr.projects import fetch_projects_on_page, _try_open_unlocked_tab


async def main() -> None:
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        result = await fetch_projects_on_page(page)
        project = next(p for p in result.projects if p.name == "Shreya - PSR data")
        pid = project.project_id

        paths = [
            f"/emp/rdb/project/{pid}/candidate-pipeline",
            f"/emp/rdb/project/{pid}/unlocked",
            f"/emp/rdb/project/{pid}/unlocked-candidates",
            f"/emp/rdb/project/{pid}/candidates/unlocked",
            f"/emp/rdb/project/{pid}/sourcing",
        ]

        for path in paths:
            await page.goto(ZIPRECRUITER_BASE_URL + path, wait_until="networkidle", timeout=45000)
            await _try_open_unlocked_tab(page)
            text = await page.inner_text("body")
            emails = len(__import__("re").findall(r"[\w.+-]+@[\w.-]+\.\w+", text))
            print(f"\n=== {path} ===")
            print("URL:", page.url)
            print("Emails on page:", emails)
            print("Snippet:", text[200:600].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())
