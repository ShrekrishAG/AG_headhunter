"""Capture all RDB API responses on candidate-pipeline load."""

import asyncio
import json

from playwright.async_api import Response

from zr.browser import ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_BASE_URL
from zr.projects import fetch_projects_on_page


async def main() -> None:
    hits: list[tuple[str, object]] = []

    async def on_response(response: Response) -> None:
        url = response.url
        if "/api/rdb" not in url and "rdb2" not in url:
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            hits.append((url, await response.json()))
        except Exception:
            pass

    async with ziprecruiter_context() as (_, page):
        page.on("response", on_response)
        await ensure_logged_in(page)
        result = await fetch_projects_on_page(page)
        project = next(p for p in result.projects if p.name == "Shreya - PSR data")
        url = f"{ZIPRECRUITER_BASE_URL}/emp/rdb/project/{project.project_id}/candidate-pipeline"
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        unlocked = page.get_by_text("Unlocked", exact=True).first
        if await unlocked.count() > 0:
            await unlocked.click(timeout=3000)
            await page.wait_for_timeout(3000)

        print(f"Captured {len(hits)} API hits")
        for api_url, payload in hits:
            print("\nURL:", api_url)
            print(json.dumps(payload, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
