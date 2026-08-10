from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from zr.projects import Project
from zr.role_config import default_role_slug, get_role, parse_role_from_text, resolve_role_slug, strip_role_tokens

TOP_N_RE = re.compile(
    r"(?:unlock|review|qualify|score)\s+(?:top\s+)?(\d+)",
    re.I,
)
POOL_RE = re.compile(
    r"(?:review|scan|check)\s+(\d+)\s+(?:locked\s+)?candidates?",
    re.I,
)
IN_PROJECT_RE = re.compile(r"\bin\s+(.+)$", re.I)
PER_PROJECT_RE = re.compile(
    r"(\d+)\s*(?:candidates?\s*)?(?:per|from each|each)\s*project",
    re.I,
)
PROJECT_LIMIT_RE = re.compile(r"([^=,\n]+?)\s*=\s*(\d+)")


def project_option_value(project: Project) -> str:
    """Stable id used in Slack multi-select option values."""
    if project.project_id:
        value = project.project_id.strip()
        return value if len(value) <= 75 else value[:74] + "…"
    digest = hashlib.sha1(project.name.strip().lower().encode("utf-8")).hexdigest()[:20]
    return f"nh:{digest}"


def project_matches_option_value(project: Project, value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if project.project_id:
        pid = project.project_id.strip()
        if pid == value or pid.startswith(value.rstrip("…")):
            return True
    return value == project_option_value(project)


@dataclass
class ReviewOptions:
    unlock_top_n: int = 5
    review_pool: int = 25
    project_query: str = ""
    default_unlock_per_project: int | None = None
    default_review_pool: int | None = None
    project_unlock_limits: dict[str, int] = field(default_factory=dict)
    project_review_pools: dict[str, int] = field(default_factory=dict)
    # When set (modal project multi-select), only these projects are reviewed.
    # Values are ZR project ids and/or "name:<lowered name>" keys.
    selected_project_ids: set[str] = field(default_factory=set)
    role_slug: str = field(default_factory=default_role_slug)
    role_explicit: bool = False

    def role_title(self) -> str:
        return get_role(self.role_slug).title

    @property
    def is_multi_project(self) -> bool:
        return bool(
            self.default_unlock_per_project is not None
            or self.project_unlock_limits
            or self.selected_project_ids
        )

    def _project_selected(self, project: Project) -> bool:
        if not self.selected_project_ids:
            return True
        return any(
            project_matches_option_value(project, key) for key in self.selected_project_ids
        )

    def _lookup_limit(
        self,
        project: Project,
        limits: dict[str, int],
        default: int | None,
    ) -> int | None:
        if project.project_id:
            by_id = limits.get(project.project_id)
            if by_id is not None:
                return by_id

        project_name = project.name.lower()
        by_name = limits.get(project_name)
        if by_name is not None:
            return by_name

        for key, count in limits.items():
            if key in project_name or project_name in key:
                return count

        return default

    def unlock_for_project(self, project: Project) -> int:
        if self.is_multi_project:
            limit = self._lookup_limit(
                project,
                self.project_unlock_limits,
                self.default_unlock_per_project,
            )
            return max(1, int(limit or self.unlock_top_n))

        if self.project_query:
            return max(1, self.unlock_top_n)

        return max(1, self.unlock_top_n)

    def review_pool_for_project(self, project: Project) -> int:
        pool = self._lookup_limit(
            project,
            self.project_review_pools,
            self.default_review_pool,
        )
        if pool is None:
            pool = self.review_pool
        unlock_n = self.unlock_for_project(project)
        return max(int(pool), unlock_n)

    def matches_project_query(self, project: Project) -> bool:
        if not self.project_query.strip():
            return True
        query = self.project_query.strip().lower()
        name = project.name.lower()
        return query == name or query in name or name in query

    def should_review_project(self, project: Project) -> bool:
        if not self.matches_project_query(project):
            return False

        if not self._project_selected(project):
            return False

        if not self.is_multi_project:
            return True

        # Explicit project multi-select from the Slack form
        if self.selected_project_ids:
            return True

        if self.default_unlock_per_project is not None:
            return True

        project_name = project.name.lower()
        if project_name in self.project_unlock_limits:
            return True

        for key in self.project_unlock_limits:
            if key in project_name or project_name in key:
                return True
        return False

    def summary_line(self) -> str:
        if self.is_multi_project:
            selected = ""
            if self.selected_project_ids:
                selected = f", *{len(self.selected_project_ids)}* project(s) selected"
            if self.project_unlock_limits and self.default_unlock_per_project is not None:
                return (
                    f"Unlock top *{self.default_unlock_per_project}* per project "
                    f"(review pool *{self.default_review_pool or self.review_pool}*, "
                    f"{len(self.project_unlock_limits)} override(s){selected})"
                )
            if self.project_unlock_limits and not self.selected_project_ids:
                parts = [
                    f"{name}={count}" for name, count in self.project_unlock_limits.items()
                ]
                return f"Per-project unlock limits: {', '.join(parts)}"
            if self.default_unlock_per_project is not None:
                return (
                    f"Unlock top *{self.default_unlock_per_project}* per project "
                    f"(review pool *{self.default_review_pool or self.review_pool}*"
                    f"{selected})"
                )
            if self.selected_project_ids:
                return (
                    f"Review *{len(self.selected_project_ids)}* selected project(s) "
                    f"(unlock top *{self.unlock_top_n}*, "
                    f"pool *{self.default_review_pool or self.review_pool}*)"
                )

        parts = [
            f"Role: *{self.role_title()}*",
            f"Review pool: *{self.review_pool}* locked candidates",
            f"Unlock top: *{self.unlock_top_n}*",
        ]
        if self.project_query:
            parts.append(f"Project: *{self.project_query}*")
        return " · ".join(parts)


def parse_review_options(text: str) -> ReviewOptions:
    options = ReviewOptions()
    if not text.strip():
        return options

    cleaned = re.sub(
        r"^(?:zr[- ]?review|review\s+pipeline|pipeline\s+review)\s*:?\s*",
        "",
        text.strip(),
        flags=re.I,
    )

    role = parse_role_from_text(cleaned)
    if role:
        options.role_explicit = True
    cleaned = strip_role_tokens(cleaned)

    for match in PROJECT_LIMIT_RE.finditer(cleaned):
        project_name = match.group(1).strip().lower()
        count = int(match.group(2))
        if count > 0:
            options.project_unlock_limits[project_name] = count

    per_project_match = PER_PROJECT_RE.search(cleaned)
    if per_project_match:
        options.default_unlock_per_project = int(per_project_match.group(1))

    for pattern in (TOP_N_RE,):
        match = pattern.search(cleaned)
        if match:
            value = int(match.group(1))
            if value > 0:
                options.unlock_top_n = value
                if options.default_unlock_per_project is None:
                    options.default_unlock_per_project = value
            break

    pool_match = POOL_RE.search(cleaned)
    if pool_match:
        value = int(pool_match.group(1))
        if value > 0:
            options.review_pool = max(value, options.unlock_top_n)
            options.default_review_pool = options.review_pool

    project_match = IN_PROJECT_RE.search(cleaned)
    if project_match:
        options.project_query = project_match.group(1).strip().strip('"').strip("'")

    options.role_slug = resolve_role_slug(
        explicit_role=role,
        project_query=options.project_query,
    )

    return options


def parse_slack_review_modal_values(values: dict) -> ReviewOptions:
    options = ReviewOptions()

    role_block = values.get("role_block", {})
    role_select = role_block.get("role_slug", {})
    role_value = (role_select.get("selected_option") or {}).get("value")
    if role_value:
        options.role_slug = role_value
        options.role_explicit = True

    projects_block = values.get("projects_block", {})
    projects_select = projects_block.get("project_ids", {})
    selected_options = projects_select.get("selected_options") or []
    for opt in selected_options:
        value = (opt.get("value") or "").strip()
        if value:
            options.selected_project_ids.add(value)

    unlock_block = values.get("default_unlock_block", {})
    unlock_input = unlock_block.get("default_unlock", {})
    unlock_value = (unlock_input.get("value") or "").strip()
    if unlock_value:
        parsed = int(unlock_value)
        if parsed > 0:
            options.default_unlock_per_project = parsed
            options.unlock_top_n = parsed

    pool_block = values.get("default_review_pool_block", {})
    pool_input = pool_block.get("default_review_pool", {})
    pool_value = (pool_input.get("value") or "").strip()
    if pool_value:
        parsed = int(pool_value)
        if parsed > 0:
            options.default_review_pool = parsed
            options.review_pool = parsed

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
                options.project_unlock_limits[name.strip().lower()] = count

    return options
