"""Probe ZipRecruiter RDB URLs and page links."""

import asyncio
import json

from zr.browser import ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_BASE_URL
from zr.projects import fetch_projects_on_page


async def main() -> None:
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        result = await fetch_projects_on_page(page)
        project = next(p for p in result.projects if p.name == "Shreya - PSR data")

        print("Current URL:", page.url)
        print("Project:", project.name, project.project_id)

        links = await page.evaluate(
            """() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map((a) => ({
                        text: (a.innerText || '').trim().slice(0, 80),
                        href: a.getAttribute('href') || '',
                    }))
                    .filter((item) => item.href && !item.href.startsWith('#'))
                    .slice(0, 40);
            }"""
        )
        print("\nSample links on page:")
        for item in links:
            print(f"  {item['text']!r} -> {item['href']}")

        candidates = [
            f"/emp/rdb/project/{project.project_id}",
            f"/emp/rdb/projects/{project.project_id}",
            f"/emp/rdb/dashboard/project/{project.project_id}",
            f"/emp/rdb/candidates?project_id={project.project_id}",
            f"/emp/rdb/project/{project.project_id}/candidates",
            f"/resume-database/project/{project.project_id}",
        ]

        print("\n=== URL probes ===")
        for path in candidates:
            url = ZIPRECRUITER_BASE_URL + path
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                title = await page.title()
                body_snip = (await page.inner_text("body"))[:200].replace("\n", " ")
                print(
                    json.dumps(
                        {
                            "path": path,
                            "status": response.status if response else None,
                            "final_url": page.url,
                            "title": title,
                            "body_snip": body_snip,
                        }
                    )
                )
            except Exception as error:
                print(f"FAIL {path}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
