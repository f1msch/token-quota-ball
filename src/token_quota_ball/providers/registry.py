"""Dispatch quota fetches to the selected provider."""

from __future__ import annotations

from collections.abc import Callable

from ..config import PROVIDER_IDS
from .cursor import fetch_cursor
from .deepseek import fetch_deepseek
from .models import ProviderSnapshot
from .trae import fetch_trae
from .volc_agent_plan import fetch_volc_agent_plan
from .workbuddy import fetch_workbuddy

ProviderFetcher = Callable[[], ProviderSnapshot]

PROVIDERS: dict[str, ProviderFetcher] = {
    "cursor": fetch_cursor,
    "workbuddy": fetch_workbuddy,
    "volc_agent_plan": fetch_volc_agent_plan,
    "deepseek": fetch_deepseek,
    "trae": fetch_trae,
}


def normalize_provider_id(provider_id: str | None) -> str:
    pid = (provider_id or "cursor").strip().lower()
    return pid if pid in PROVIDER_IDS else "cursor"


def fetch_provider(provider_id: str) -> ProviderSnapshot:
    pid = normalize_provider_id(provider_id)
    fetcher = PROVIDERS.get(pid) or PROVIDERS["cursor"]
    return fetcher()
