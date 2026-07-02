"""Debug project URLs and open-project navigation."""

import asyncio
import json

from zr.browser import ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_RDB_URL
from zr.projects import (
    _projects_from_dom,
    enrich_projects_with_urls,
    fetch_projects_on_page,
    open_project,
)


async def main() -> None:
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        result = await fetch_projects_on_page(page)
        projects = [p for p in result.projects if p.unlocked_count not in (None, 0)][:3]
        projects = await enrich_projects_with_urls(page, projects)

        print("=== Projects (first 3 with unlocks) ===")
        for project in projects:
            print(
                json.dumps(
                    {
                        "name": project.name,
                        "project_id": project.project_id,
                        "url": project.url,
                        "unlocked_count": project.unlocked_count,
                    },
                    indent=2,
                )
            )

        await page.goto(ZIPRECRUITER_RDB_URL, wait_until="networkidle")
        dom = await _projects_from_dom(page)
        print("\n=== DOM project links ===")
        for item in dom[:10]:
            print(f"  {item.name!r} -> {item.url!r}")

        print("\n=== Try open_project ===")
        for project in projects[:2]:
            try:
                await open_project(page, project)
                print(f"OK  {project.name} -> {page.url}")
            except Exception as error:
                print(f"FAIL {project.name}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
