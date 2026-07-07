"""Slack review sessions for unlock/export confirmation buttons."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zr.config import BASE_DIR
from zr.locked_pipeline import LockedCandidate
from zr.pipeline_review import PipelineReviewResult, ProjectReviewSlice
from zr.projects import Project

logger = logging.getLogger(__name__)

SESSION_DIR = BASE_DIR / ".review-sessions"


@dataclass
class ReviewSession:
    session_id: str
    channel: str
    thread_ts: str | None
    slices: list[ProjectReviewSlice] = field(default_factory=list)

    @property
    def total_unlock_count(self) -> int:
        return sum(len(slice_.top_candidates) for slice_ in self.slices)

    @property
    def project(self) -> Project:
        return self.slices[0].project

    @property
    def reviewed_count(self) -> int:
        return sum(slice_.reviewed_count for slice_ in self.slices)

    @property
    def unlock_top_n(self) -> int:
        return self.slices[0].unlock_top_n if self.slices else 0

    @property
    def ranked(self) -> list[LockedCandidate]:
        return self.slices[0].ranked if self.slices else []

    def top_to_unlock(self) -> list[LockedCandidate]:
        selected: list[LockedCandidate] = []
        for slice_ in self.slices:
            selected.extend(slice_.top_candidates)
        return selected

    def export_project_limits(self) -> dict[str, int]:
        limits: dict[str, int] = {}
        for slice_ in self.slices:
            count = len(slice_.top_candidates)
            if count <= 0:
                continue
            if slice_.project.project_id:
                limits[slice_.project.project_id] = count
            limits[slice_.project.name.lower()] = count
        return limits

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "thread_ts": self.thread_ts,
            "slices": [_slice_to_payload(slice_) for slice_ in self.slices],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReviewSession":
        slices = [_slice_from_payload(item) for item in payload.get("slices") or []]
        return cls(
            session_id=str(payload.get("session_id") or ""),
            channel=str(payload.get("channel") or ""),
            thread_ts=payload.get("thread_ts"),
            slices=slices,
        )


_sessions: dict[str, ReviewSession] = {}


def _session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def _candidate_to_payload(candidate: LockedCandidate) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "pipeline_index": candidate.pipeline_index,
        "total_score": candidate.total_score,
        "recommendation": candidate.recommendation,
        "summary": candidate.summary,
        "qualifies": candidate.qualifies,
        "encrypted_jobseeker_id": candidate.encrypted_jobseeker_id,
    }


def _candidate_from_payload(payload: dict[str, Any]) -> LockedCandidate:
    return LockedCandidate(
        name=str(payload.get("name") or "Candidate"),
        pipeline_index=int(payload.get("pipeline_index") or 1),
        total_score=payload.get("total_score"),
        recommendation=payload.get("recommendation"),
        summary=payload.get("summary"),
        qualifies=payload.get("qualifies"),
        encrypted_jobseeker_id=str(payload.get("encrypted_jobseeker_id") or ""),
    )


def _slice_to_payload(slice_: ProjectReviewSlice) -> dict[str, Any]:
    return {
        "project": {
            "name": slice_.project.name,
            "project_id": slice_.project.project_id,
            "owner": slice_.project.owner,
            "location": slice_.project.location,
            "job_title": slice_.project.job_title,
            "url": slice_.project.url,
            "unlocked_count": slice_.project.unlocked_count,
        },
        "reviewed_count": slice_.reviewed_count,
        "unlock_top_n": slice_.unlock_top_n,
        "ranked": [_candidate_to_payload(candidate) for candidate in slice_.ranked],
    }


def _slice_from_payload(payload: dict[str, Any]) -> ProjectReviewSlice:
    project_data = payload.get("project") or {}
    project = Project(
        name=str(project_data.get("name") or ""),
        owner=str(project_data.get("owner") or ""),
        location=str(project_data.get("location") or ""),
        job_title=str(project_data.get("job_title") or ""),
        project_id=str(project_data.get("project_id") or ""),
        url=str(project_data.get("url") or ""),
        unlocked_count=project_data.get("unlocked_count"),
    )
    ranked = [
        _candidate_from_payload(item) for item in (payload.get("ranked") or [])
    ]
    return ProjectReviewSlice(
        project=project,
        reviewed_count=int(payload.get("reviewed_count") or 0),
        unlock_top_n=int(payload.get("unlock_top_n") or 0),
        ranked=ranked,
    )


def _save_session(session: ReviewSession) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(session.session_id)
    path.write_text(json.dumps(session.to_payload(), indent=2), encoding="utf-8")


def create_session(
    *,
    channel: str,
    thread_ts: str | None,
    result: PipelineReviewResult,
) -> ReviewSession:
    session_id = uuid.uuid4().hex[:12]
    session = ReviewSession(
        session_id=session_id,
        channel=channel,
        thread_ts=thread_ts,
        slices=list(result.slices),
    )
    _sessions[session_id] = session
    _save_session(session)
    return session


def get_session(session_id: str) -> ReviewSession | None:
    if not session_id:
        return None

    cached = _sessions.get(session_id)
    if cached:
        return cached

    path = _session_path(session_id)
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        session = ReviewSession.from_payload(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        logger.warning("Could not load review session %s: %s", session_id, error)
        return None

    _sessions[session_id] = session
    return session


def update_session(session: ReviewSession) -> None:
    _sessions[session.session_id] = session
    _save_session(session)


def drop_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
    path = _session_path(session_id)
    if path.is_file():
        path.unlink(missing_ok=True)
