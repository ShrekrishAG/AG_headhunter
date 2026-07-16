"""Manager market config — ZR project → GMs for sales packet distribution."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from lib.constants import DASHBOARD_ROOT

CONFIG_PATH = DASHBOARD_ROOT / "config" / "manager_markets.yaml"


@dataclass(frozen=True)
class MarketManagers:
    project: str
    market: str
    manager_emails: tuple[str, ...]


@lru_cache(maxsize=1)
def load_market_managers(config_path: Path | None = None) -> list[MarketManagers]:
    path = config_path or CONFIG_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    markets: list[MarketManagers] = []
    for entry in raw.get("markets") or []:
        emails = []
        for manager in entry.get("managers") or []:
            email = str(manager.get("email") or "").strip().lower()
            if email and "@" in email and not email.startswith("caine???"):
                emails.append(email)
        if not emails:
            continue
        markets.append(
            MarketManagers(
                project=str(entry.get("project") or "").strip(),
                market=str(entry.get("market") or "").strip(),
                manager_emails=tuple(emails),
            )
        )
    return markets


def project_to_market_map() -> dict[str, MarketManagers]:
    mapping: dict[str, MarketManagers] = {}
    for market in load_market_managers():
        mapping[market.project.lower()] = market
        mapping[market.project] = market
    return mapping


def resolve_market(project_name: str | None) -> MarketManagers | None:
    if not project_name:
        return None
    key = project_name.strip()
    by_project = project_to_market_map()
    if key in by_project:
        return by_project[key]
    lower = key.lower()
    if lower in by_project:
        return by_project[lower]
    for market in load_market_managers():
        if market.project.lower() in lower or lower in market.project.lower():
            return market
    return None


def configured_projects() -> list[str]:
    return [m.project for m in load_market_managers()]
