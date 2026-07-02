"""Probe candidate contact info on candidate-pipeline page."""

import asyncio
import re

from playwright.async_api import Response

from zr.browser import ensure_logged_in, ziprecruiter_context
from zr.config import ZIPRECRUITER_BASE_URL
from zr.projects import fetch_projects_on_page


async def main() -> None:
    captured: list[str] = []

    async def on_response(response: Response) -> None:
        url = response.url
        if "candidate" not in url.lower() and "pipeline" not in url.lower():
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            body = await response.json()
            text = str(body)
            if "@" in text or "phone" in text.lower():
                captured.append(f"{url}\n{text[:500]}")
        except Exception:
            pass

    async with ziprecruiter_context() as (_, page):
        page.on("response", on_response)
        await ensure_logged_in(page)
        result = await fetch_projects_on_page(page)
        project = next(p for p in result.projects if p.name == "Shreya - PSR data")
        url = f"{ZIPRECRUITER_BASE_URL}/emp/rdb/project/{project.project_id}/candidate-pipeline"
        await page.goto(url, wait_until="networkidle")

        for label in ("View All Unlocked", "Unlocked"):
            loc = page.get_by_text(label, exact=False).first
            if await loc.count() > 0:
                try:
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(2000)
                    print("Clicked:", label)
                    break
                except Exception:
                    pass

        rows = await page.evaluate(
            """() => {
                return Array.from(document.querySelectorAll('tr, [class*="candidate"], article'))
                    .map((el) => (el.innerText || '').trim())
                    .filter((text) => text.length > 10 && text.length < 400)
                    .slice(0, 10);
            }"""
        )
        print("\nRows:")
        for row in rows:
            print("-", row.replace("\n", " | ")[:200])

        # Click first candidate name link/button
        candidate = page.get_by_text("Eric Boutell", exact=False).first
        if await candidate.count() > 0:
            await candidate.click(timeout=5000)
            await page.wait_for_timeout(3000)
            text = await page.inner_text("body")
            emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", text)
            phones = re.findall(r"\+?\d[\d\s().-]{8,}\d", text)
            print("\nAfter click emails:", emails[:5])
            print("After click phones:", phones[:5])

        print("\nCaptured JSON responses:", len(captured))
        for item in captured[:5]:
            print(item[:600])
            print("---")


if __name__ == "__main__":
    asyncio.run(main())
