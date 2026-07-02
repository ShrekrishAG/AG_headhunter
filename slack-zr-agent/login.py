import argparse
import asyncio

from zr.browser import interactive_login


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log into ZipRecruiter and save browser session.")
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="Connect to a normal Chrome window you open manually (best for Cloudflare).",
    )
    args = parser.parse_args()
    asyncio.run(interactive_login(use_cdp=args.cdp))
