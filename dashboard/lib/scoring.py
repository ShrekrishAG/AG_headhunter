"""Scoring helpers."""

from __future__ import annotations

from typing import Any

from lib.constants import (
    DIMENSIONS,
    GATES,
    INTERVIEWERS,
    R1_CONSIDER_THRESHOLD,
    R1_RECOMMEND_THRESHOLD,
)


def compute_weighted_score(scores: dict[str, int | None]) -> float | None:
    if any(scores.get(dim["score_key"]) is None for dim in DIMENSIONS):
        return None
    total = sum(scores[dim["score_key"]] * dim["weight"] for dim in DIMENSIONS)
    return round(total, 2)


def gates_passed(gates: dict[str, bool | None]) -> bool:
    return all(gates.get(key) for key, _ in GATES)


def recommendation_label(weighted: float | None, gates_ok: bool) -> str:
    if not gates_ok:
        return "Pass (gate fail)"
    if weighted is None:
        return "Incomplete"
    if weighted >= R1_RECOMMEND_THRESHOLD:
        return "Recommend"
    if weighted >= R1_CONSIDER_THRESHOLD:
        return "Consider"
    return "Pass"


def combined_r1_decision(*votes: str | None) -> str:
    keys = list(INTERVIEWERS.keys())
    if len(keys) < 2:
        return "Configure at least two interviewers"
    vote_a, vote_b = votes[0] if votes else None, votes[1] if len(votes) > 1 else None
    if not vote_a or not vote_b:
        return "Pending both scoresheets"
    if vote_a == "pass" or vote_b == "pass":
        return "Pass"
    if vote_a == "hold" or vote_b == "hold":
        return "Hold"
    if vote_a == "advance" and vote_b == "advance":
        return "Unanimous Advance → Round 2"
    return "Split — debrief required"


def format_vote(vote: str | None) -> str:
    if not vote:
        return "—"
    return vote.replace("_", " ").title()
