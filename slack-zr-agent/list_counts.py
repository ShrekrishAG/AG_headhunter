"""Quick local test: print unlocked counts per project."""

import asyncio

from zr.projects import fetch_projects, format_projects_for_slack


async def main() -> None:
    result = await fetch_projects()
    print(format_projects_for_slack(result))


if __name__ == "__main__":
    asyncio.run(main())
