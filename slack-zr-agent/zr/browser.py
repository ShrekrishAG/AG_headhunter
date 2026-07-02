from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import BrowserContext, Page, async_playwright

from zr.config import (
    BROWSER_DATA_DIR,
    CHROME_CDP_URL,
    LOGIN_TIMEOUT_MS,
    NAVIGATION_TIMEOUT_MS,
    PLAYWRIGHT_CHANNEL,
    PLAYWRIGHT_HEADLESS,
    ZIPRECRUITER_BASE_URL,
    ZIPRECRUITER_RDB_URL,
)

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, "webdriver", { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
"""


class ZipRecruiterSessionError(Exception):
    pass


def _is_cloudflare_challenge(page_text: str) -> bool:
    lowered = page_text.lower()
    return (
        "performing security verification" in lowered
        or "verify you are human" in lowered
        or "checking your browser" in lowered
    )


def _looks_logged_in(url: str, page_text: str) -> bool:
    if _is_cloudflare_challenge(page_text):
        return False

    lowered = page_text.lower()
    if "sign in" in lowered and "resume database" not in lowered:
        return False
    if "/login" in url or "/signin" in url or "/sign-in" in url:
        return False
    return True


async def _apply_stealth(page: Page) -> None:
    await page.add_init_script(STEALTH_INIT_SCRIPT)


async def _launch_persistent_context(playwright, *, headless: bool) -> BrowserContext:
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict = {
        "user_data_dir": str(BROWSER_DATA_DIR),
        "headless": headless,
        "viewport": {"width": 1440, "height": 900},
        "args": STEALTH_ARGS,
        "ignore_default_args": ["--enable-automation"],
    }

    if PLAYWRIGHT_CHANNEL:
        launch_kwargs["channel"] = PLAYWRIGHT_CHANNEL

    last_error: Exception | None = None

    for attempt_headless in (headless, False):
        attempt_kwargs = {**launch_kwargs, "headless": attempt_headless}
        for use_channel in (True, False):
            kwargs = dict(attempt_kwargs)
            if not use_channel:
                kwargs.pop("channel", None)
            try:
                return await playwright.chromium.launch_persistent_context(**kwargs)
            except Exception as error:
                last_error = error

    raise ZipRecruiterSessionError(
        "Could not launch browser for ZipRecruiter. "
        "Run `playwright install chromium` and `python login.py`, "
        "or set PLAYWRIGHT_HEADLESS=false in .env. "
        f"Details: {last_error}"
    )


@asynccontextmanager
async def ziprecruiter_context() -> AsyncIterator[tuple[BrowserContext, Page]]:
    async with async_playwright() as playwright:
        if CHROME_CDP_URL:
            browser = await playwright.chromium.connect_over_cdp(CHROME_CDP_URL)
            if not browser.contexts:
                raise ZipRecruiterSessionError(
                    "Connected to Chrome over CDP but no browser context was found."
                )
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            await _apply_stealth(page)
            page.set_default_timeout(NAVIGATION_TIMEOUT_MS)
            try:
                yield context, page
            finally:
                await browser.close()
            return

        context = await _launch_persistent_context(playwright, headless=PLAYWRIGHT_HEADLESS)
        page = context.pages[0] if context.pages else await context.new_page()
        await _apply_stealth(page)
        page.set_default_timeout(NAVIGATION_TIMEOUT_MS)
        try:
            yield context, page
        finally:
            await context.close()


async def ensure_logged_in(page: Page) -> str:
    await page.goto(ZIPRECRUITER_RDB_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)

    url = page.url
    body_text = await page.inner_text("body")

    if _is_cloudflare_challenge(body_text):
        raise ZipRecruiterSessionError(
            "Cloudflare blocked the automated browser. "
            "Run `python login.py` and complete the 'Verify you are human' checkbox, "
            "or use `python login.py --cdp` with your normal Chrome window."
        )

    if not _looks_logged_in(url, body_text):
        raise ZipRecruiterSessionError(
            "ZipRecruiter session is not active. Run `python login.py` once to sign in, "
            "then try again from Slack."
        )

    return url


async def interactive_login(use_cdp: bool = False) -> None:
    """Open a visible browser so the user can log in manually once."""
    if use_cdp:
        print("\n=== CDP login mode ===")
        print("1. Quit Chrome completely.")
        print("2. In a separate terminal, run:\n")
        print(
            '   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome '
            f'--remote-debugging-port=9222 --user-data-dir="{BROWSER_DATA_DIR}"\n'
        )
        print("3. In that Chrome window:")
        print("   - Go to https://www.ziprecruiter.com")
        print("   - Complete the Cloudflare checkbox if shown")
        print("   - Log in and open Resume Database")
        print("4. Press Enter here when your projects dashboard is visible...")
        input()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
            print("Connected to Chrome. Session is stored in your Chrome profile.")
            print(f"Profile directory: {BROWSER_DATA_DIR}")
            print(
                "\nSet this in .env so the Slack agent reuses the same profile:\n"
                f'CHROME_CDP_URL=http://localhost:9222\n'
                f'BROWSER_DATA_DIR={BROWSER_DATA_DIR}'
            )
            await browser.close()
        return

    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        context = await _launch_persistent_context(playwright, headless=False)
        page = context.pages[0] if context.pages else await context.new_page()
        await _apply_stealth(page)

        await page.goto(ZIPRECRUITER_BASE_URL, wait_until="domcontentloaded")

        print("\n=== ZipRecruiter login ===")
        print("A Chrome window should have opened.")
        print("\nIf you see 'Performing security verification':")
        print("  1. Click the 'Verify you are human' checkbox")
        print("  2. Wait for the page to load")
        print("\nThen:")
        print("  3. Log into ZipRecruiter")
        print("  4. Open Resume Database and go to your projects dashboard")
        print("  5. Come back here and press Enter\n")

        try:
            await page.wait_for_function(
                """() => {
                    const text = document.body?.innerText?.toLowerCase() || '';
                    return location.href.includes('resume-database')
                      || text.includes('projects');
                }""",
                timeout=LOGIN_TIMEOUT_MS,
            )
        except Exception:
            pass

        input("Press Enter when you can see your Resume Database projects...")
        await context.close()
        print(f"\nSession saved to {BROWSER_DATA_DIR}")
        print("You can now run `python main.py` and use /zr-projects in Slack.")
