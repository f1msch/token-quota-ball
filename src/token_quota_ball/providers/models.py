"""多提供方额度快照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from ..config import PROVIDER_META
from ..platform.logging_setup import now_beijing

if TYPE_CHECKING:
    from .cursor.usage import QuotaSnapshot

STATUS_OK = "ok"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class MeterRow:
    key: str
    title: str
    value: str
    percent: float | None = None
    color: str = "#5ecf8c"
    detail: str = ""


@dataclass(frozen=True)
class ProviderSnapshot:
    provider_id: str
    title: str
    account: str = ""
    plan: str = ""
    display_text: str = "--"
    percent_used: float | None = None
    status: str = STATUS_OK
    error: str | None = None
    rows: tuple[MeterRow, ...] = ()
    extras: tuple[str, ...] = ()
    notes: str = ""
    fetched_at: datetime = field(default_factory=now_beijing)
    cursor: "QuotaSnapshot | None" = None

    @property
    def subtitle(self) -> str:
        parts = [part for part in (self.plan, self.account) if part]
        return "  ·  ".join(parts)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and not self.error


def _meta(provider_id: str) -> dict[str, str]:
    return PROVIDER_META.get(provider_id, {"title": provider_id})


def unconfigured_snapshot(provider_id: str, message: str, notes: str = "") -> ProviderSnapshot:
    meta = _meta(provider_id)
    return ProviderSnapshot(
        provider_id=provider_id,
        title=meta["title"],
        display_text="--",
        percent_used=None,
        status=STATUS_UNCONFIGURED,
        error=message,
        notes=notes,
        extras=(message,),
    )


def error_snapshot(provider_id: str, message: str, notes: str = "") -> ProviderSnapshot:
    meta = _meta(provider_id)
    return ProviderSnapshot(
        provider_id=provider_id,
        title=meta["title"],
        display_text="--",
        percent_used=None,
        status=STATUS_ERROR,
        error=message,
        notes=notes,
        extras=(message,),
    )


def format_number(value: float, unit: str = "") -> str:
    if abs(value - round(value)) < 1e-9 and abs(value) >= 10:
        text = f"{int(round(value))}"
    elif abs(value) >= 100:
        text = f"{value:.0f}"
    elif abs(value) >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}{unit}" if unit else text


def used_percent(used: float | None, limit: float | None, remaining: float | None = None) -> float | None:
    if limit is None or limit <= 0:
        return None
    if used is None and remaining is not None:
        used = max(0.0, limit - remaining)
    if used is None:
        return None
    return max(0.0, min(100.0, used / limit * 100.0))


def meter_color(pct: float | None) -> str:
    if pct is None:
        return "#5a6a7a"
    if pct >= 95:
        return "#ff6b73"
    if pct >= 80:
        return "#ffc24a"
    return "#3ee89a"
