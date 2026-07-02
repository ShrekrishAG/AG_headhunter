import argparse
import asyncio

from zr.export import export_all_candidates, format_export_for_slack
from zr.export_options import ExportOptions, parse_export_options


def _build_options(args: argparse.Namespace) -> ExportOptions:
    options = ExportOptions()
    if args.limit is not None:
        options.default_per_project_limit = args.limit

    for item in args.project_limit or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --project-limit value: {item!r}. Use Project Name=5")
        name, count_text = item.split("=", 1)
        count = int(count_text.strip())
        if count > 0:
            options.project_limits[name.strip().lower()] = count

    if args.text:
        parsed = parse_export_options(args.text)
        if parsed.default_per_project_limit is not None:
            options.default_per_project_limit = parsed.default_per_project_limit
        options.project_limits.update(parsed.project_limits)

    return options


async def main() -> None:
    parser = argparse.ArgumentParser(description="Export ZipRecruiter unlocked candidates.")
    parser.add_argument(
        "--limit",
        type=int,
        help="Max candidates to export from each project (default: all)",
    )
    parser.add_argument(
        "--project-limit",
        action="append",
        metavar="NAME=COUNT",
        help="Override limit for one project (repeatable)",
    )
    parser.add_argument(
        "--text",
        help='Natural language limits, e.g. "5 per project" or "Seattle=10, NYC=5"',
    )
    args = parser.parse_args()

    options = _build_options(args)
    result = await export_all_candidates(options)
    print(format_export_for_slack(result))


if __name__ == "__main__":
    asyncio.run(main())
