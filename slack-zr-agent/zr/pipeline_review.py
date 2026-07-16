"""Review locked pipeline candidates, rank by AI score, unlock top N."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from zr.browser import ZipRecruiterSessionError, ensure_logged_in, ziprecruiter_context
from zr.config import PIPELINE_REVIEW_POOL
from zr.locked_pipeline import LockedCandidate, scrape_locked_candidates, unlock_candidates
from zr.pipeline_prescreen import recommendation_emoji, score_candidates
from zr.projects import Project, fetch_projects_on_page
from zr.review_options import ReviewOptions
from zr.role_config import resolve_role_slug

logger = logging.getLogger(__name__)


@dataclass
class ProjectReviewSlice:
    project: Project
    reviewed_count: int
    unlock_top_n: int
    ranked: list[LockedCandidate] = field(default_factory=list)

    @property
    def top_candidates(self) -> list[LockedCandidate]:
        return self.ranked[: self.unlock_top_n]


@dataclass
class PipelineReviewResult:
    slices: list[ProjectReviewSlice] = field(default_factory=list)
    options: ReviewOptions | None = None

    @property
    def is_multi_project(self) -> bool:
        return len(self.slices) > 1

    @property
    def total_unlock_count(self) -> int:
        return sum(len(slice_.top_candidates) for slice_ in self.slices)

    @property
    def total_reviewed_count(self) -> int:
        return sum(slice_.reviewed_count for slice_ in self.slices)

    # Backward-compatible single-project accessors
    @property
    def project(self) -> Project:
        if not self.slices:
            raise ValueError("No project slices in review result")
        return self.slices[0].project

    @property
    def reviewed_count(self) -> int:
        return self.slices[0].reviewed_count if self.slices else 0

    @property
    def unlock_top_n(self) -> int:
        return self.slices[0].unlock_top_n if self.slices else 0

    @property
    def ranked(self) -> list[LockedCandidate]:
        return self.slices[0].ranked if self.slices else []

    @property
    def top_candidates(self) -> list[LockedCandidate]:
        return self.slices[0].top_candidates if self.slices else []


def resolve_project(projects: list[Project], query: str) -> Project:
    cleaned = query.strip().lower()
    if not cleaned:
        if len(projects) == 1:
            return projects[0]
        names = ", ".join(project.name for project in projects[:8])
        raise ZipRecruiterSessionError(
            "Multiple projects found. Specify one with `in Project Name`, "
            "or use `/zr-review` to open the form.\n"
            f"Examples: {names}"
        )

    exact = [project for project in projects if project.name.lower() == cleaned]
    if len(exact) == 1:
        return exact[0]

    partial = [
        project
        for project in projects
        if cleaned in project.name.lower() or project.name.lower() in cleaned
    ]
    if len(partial) == 1:
        return partial[0]

    if len(partial) > 1:
        names = ", ".join(project.name for project in partial[:8])
        raise ZipRecruiterSessionError(
            f"Multiple projects match `{query}`: {names}. Be more specific."
        )

    raise ZipRecruiterSessionError(
        f"No project matches `{query}`. Run `/zr-projects` to see names."
    )


async def _review_single_project(
    page,
    project: Project,
    options: ReviewOptions,
) -> ProjectReviewSlice:
    review_pool = options.review_pool_for_project(project)
    unlock_top_n = options.unlock_for_project(project)

    locked = await scrape_locked_candidates(page, project, limit=review_pool)
    scored = await asyncio.to_thread(
        score_candidates, locked, role_slug=options.role_slug
    )
    ranked = sorted(
        scored,
        key=lambda candidate: (
            candidate.total_score or 0,
            candidate.qualifies or False,
        ),
        reverse=True,
    )

    return ProjectReviewSlice(
        project=project,
        reviewed_count=len(locked),
        unlock_top_n=unlock_top_n,
        ranked=ranked,
    )


async def run_pipeline_review(options: ReviewOptions) -> PipelineReviewResult:
    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        project_result = await fetch_projects_on_page(page)
        if not project_result.projects:
            raise ZipRecruiterSessionError("No ZipRecruiter projects found.")

        projects = project_result.projects
        slices: list[ProjectReviewSlice] = []

        if options.is_multi_project:
            targets = [
                project
                for project in projects
                if project.project_id and options.should_review_project(project)
            ]
            if not targets:
                raise ZipRecruiterSessionError(
                    "No matching projects found for review. "
                    "Check project names in the form overrides."
                )
            for project in targets:
                try:
                    slices.append(await _review_single_project(page, project, options))
                except ZipRecruiterSessionError as error:
                    logger.warning("Skipping project %s: %s", project.name, error)
            if not slices:
                raise ZipRecruiterSessionError(
                    "Could not review any projects. Check ZipRecruiter login and pipeline access."
                )
        else:
            project = resolve_project(projects, options.project_query)
            if not project.project_id:
                raise ZipRecruiterSessionError(
                    f"Project `{project.name}` is missing a project id."
                )
            if not options.role_explicit:
                options.role_slug = resolve_role_slug(project_query=project.name)
            slices.append(await _review_single_project(page, project, options))

        return PipelineReviewResult(slices=slices, options=options)


async def unlock_review_top(result: PipelineReviewResult) -> dict[str, list[LockedCandidate]]:
    unlocked_by_project: dict[str, list[LockedCandidate]] = {}

    async with ziprecruiter_context() as (_, page):
        await ensure_logged_in(page)
        for slice_ in result.slices:
            targets = slice_.top_candidates
            if not targets:
                continue
            unlocked = await unlock_candidates(page, slice_.project, targets)
            unlocked_by_project[slice_.project.name] = unlocked

    return unlocked_by_project


def format_review_for_slack(result: PipelineReviewResult) -> str:
    lines: list[str] = []

    if result.options:
        lines.append(f"*Role:* {result.options.role_title()}")
        lines.append("")

    if result.is_multi_project:
        lines.append(
            f"*Pipeline review — {len(result.slices)} project(s)*"
        )
        lines.append(
            f"Reviewed *{result.total_reviewed_count}* locked profile(s) total. "
            f"Top picks to unlock: *{result.total_unlock_count}* candidate(s)."
        )
        lines.append("")
    else:
        slice_ = result.slices[0]
        lines.extend(
            [
                f"*Pipeline review — {slice_.project.name}*",
                f"Reviewed *{slice_.reviewed_count}* locked profile(s). "
                f"Top *{slice_.unlock_top_n}* by AI score:",
                "",
            ]
        )

    qualified_total = 0
    for slice_ in result.slices:
        if result.is_multi_project:
            lines.append(f"*{slice_.project.name}* — top {slice_.unlock_top_n}:")
        for index, candidate in enumerate(slice_.top_candidates, start=1):
            score = candidate.total_score if candidate.total_score is not None else "—"
            emoji = recommendation_emoji(candidate.recommendation)
            summary = (candidate.summary or "").strip()
            if len(summary) > 120:
                summary = summary[:117] + "..."
            prefix = f"{index}." if not result.is_multi_project else f"  {index}."
            lines.append(
                f"{prefix} *{candidate.name}* — {score}/100 {emoji} "
                f"{candidate.recommendation or '—'}"
            )
            if summary:
                lines.append(f"     _{summary}_")
            if candidate.qualifies:
                qualified_total += 1
        if result.is_multi_project:
            lines.append("")

    unlock_count = result.total_unlock_count
    lines.extend(
        [
            f"Qualified in unlock set: *{qualified_total}*",
            f"Unlock {unlock_count} candidate(s)? "
            f"(*{unlock_count} credit(s)* — confirm below)",
        ]
    )
    return "\n".join(lines)
