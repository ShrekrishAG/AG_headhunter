from __future__ import annotations

import re
from dataclasses import dataclass, field

from zr.projects import Project

PER_PROJECT_RE = re.compile(
    r"(\d+)\s*(?:candidates?\s*)?(?:per|from each|each)\s*project",
    re.I,
)
LIMIT_RE = re.compile(r"(?:limit|max)\s*[:=]?\s*(\d+)", re.I)
EXPORT_COUNT_RE = re.compile(
    r"export\s+(?:up to\s+)?(\d+)\s+candidates?",
    re.I,
)
PROJECT_LIMIT_RE = re.compile(r"([^=,\n]+?)\s*=\s*(\d+)")


@dataclass
class ExportOptions:
    default_per_project_limit: int | None = None
    project_limits: dict[str, int] = field(default_factory=dict)

    def limit_for_project(self, project: Project) -> int | None:
        if project.project_id:
            by_id = self.project_limits.get(project.project_id)
            if by_id is not None:
                return by_id

        project_name = project.name.lower()
        by_name = self.project_limits.get(project_name)
        if by_name is not None:
            return by_name

        for key, count in self.project_limits.items():
            if key in project_name or project_name in key:
                return count

        return self.default_per_project_limit

    def apply_to_candidates(self, project: Project, candidates: list) -> list:
        limit = self.limit_for_project(project)
        if limit is None or limit <= 0:
            return candidates
        return candidates[:limit]

    def should_export_project(self, project: Project) -> bool:
        if not self.project_limits or self.default_per_project_limit is not None:
            return True

        project_name = project.name.lower()
        if project_name in self.project_limits:
            return True

        for key in self.project_limits:
            if key in project_name or project_name in key:
                return True
        return False

    def summary_line(self) -> str:
        if self.project_limits and self.default_per_project_limit is not None:
            return (
                f"Limit: *{self.default_per_project_limit}* per project "
                f"(with {len(self.project_limits)} override(s))"
            )
        if self.project_limits:
            parts = [f"{name}={count}" for name, count in self.project_limits.items()]
            return f"Per-project limits: {', '.join(parts)}"
        if self.default_per_project_limit is not None:
            return f"Limit: *{self.default_per_project_limit}* candidates per project"
        return "Limit: *all* unlocked candidates per project"


def parse_export_options(text: str) -> ExportOptions:
    options = ExportOptions()
    if not text.strip():
        return options

    cleaned = re.sub(r"^export\s+candidates?\s*:?\s*", "", text.strip(), flags=re.I)

    for match in PROJECT_LIMIT_RE.finditer(cleaned):
        project_name = match.group(1).strip().lower()
        count = int(match.group(2))
        if count > 0:
            options.project_limits[project_name] = count

    for pattern in (PER_PROJECT_RE, LIMIT_RE, EXPORT_COUNT_RE):
        match = pattern.search(text)
        if match:
            options.default_per_project_limit = int(match.group(1))
            break

    return options


def parse_slack_modal_values(values: dict) -> ExportOptions:
    options = ExportOptions()

    default_block = values.get("default_limit_block", {})
    default_input = default_block.get("default_limit", {})
    default_value = (default_input.get("value") or "").strip()
    if default_value:
        parsed = int(default_value)
        if parsed > 0:
            options.default_per_project_limit = parsed

    overrides_block = values.get("project_overrides_block", {})
    overrides_input = overrides_block.get("project_overrides", {})
    overrides_text = (overrides_input.get("value") or "").strip()
    if overrides_text:
        for line in overrides_text.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, count_text = line.split("=", 1)
            count = int(count_text.strip())
            if count > 0:
                options.project_limits[name.strip().lower()] = count

    return options
