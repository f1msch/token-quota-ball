"""Cursor Included Usage provider."""

from __future__ import annotations

from ...config import PROVIDER_META
from ...formatters import format_duration, format_tokens_cn, format_usd_cents
from ..models import (
    STATUS_OK,
    MeterRow,
    ProviderSnapshot,
    error_snapshot,
    meter_color,
    unconfigured_snapshot,
)
from .usage import QuotaSnapshot, fetch_quota

def _cursor_rows(snap: QuotaSnapshot) -> tuple[MeterRow, ...]:
    rows = [
        MeterRow(
            "total",
            "Total",
            f"{snap.total_percent_used:.0f}%",
            snap.total_percent_used,
            meter_color(snap.total_percent_used),
        ),
        MeterRow(
            "fp",
            "First-Party Models",
            f"{snap.first_party_percent_used:.0f}%  {format_tokens_cn(snap.first_party_tokens)}",
            snap.first_party_percent_used,
            "#5ecf8c",
        ),
        MeterRow(
            "api",
            "API",
            f"{snap.api_percent_used:.0f}%  {format_tokens_cn(snap.api_tokens)}",
            snap.api_percent_used,
            "#c792ea",
        ),
    ]
    grok = snap.grok_bot
    if grok and grok.show_meter:
        gp = grok.usage_percent or 0.0
        rows.append(MeterRow("grok", "Grok Bot", f"{gp:.0f}%", gp, "#3ecfcf"))
    else:
        rows.append(MeterRow("grok", "Grok Bot", "--", None, "#3ecfcf"))
    credits = snap.credits
    if credits and credits.total_cents > 0:
        rows.append(
            MeterRow(
                "credit",
                "Credits",
                f"{format_usd_cents(credits.remaining_cents)}/{format_usd_cents(credits.total_cents)}",
                credits.remaining_percent,
                "#e0b050",
            )
        )
    else:
        rows.append(MeterRow("credit", "Credits", "--", None, "#e0b050"))
    return tuple(rows)


def _cursor_extras(snap: QuotaSnapshot) -> tuple[str, ...]:
    extras = [f"周期剩余 {format_duration(snap.seconds_left)}"]
    grok = snap.grok_bot
    if grok and grok.show_meter and grok.reset_at:
        extras.append(f"Grok 剩余 {format_duration(grok.seconds_left)}")
    if snap.credits and snap.credits.expires_at:
        extras.append(f"Credits 到期 {snap.credits.expires_at.strftime('%Y-%m-%d')}")
    if snap.hit_limit:
        extras.append("已达到用量限制")
    return tuple(extras)


def fetch_cursor() -> ProviderSnapshot:
    meta = PROVIDER_META["cursor"]
    try:
        snap = fetch_quota()
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "无法读取 Cursor 登录态"
        lower = message.lower()
        if "未找到" in message or "登录" in message or "filenotfound" in lower:
            return unconfigured_snapshot("cursor", message, notes="请先在 Cursor 中登录账号。")
        return error_snapshot("cursor", message)
    pct = max(0.0, min(100.0, snap.total_percent_used))
    return ProviderSnapshot(
        provider_id="cursor",
        title=meta["title"],
        account=snap.email or "",
        plan=snap.plan_name + (f"  ·  {snap.price}" if snap.price else ""),
        display_text=f"{pct:.0f}%",
        percent_used=pct,
        status=STATUS_OK,
        rows=_cursor_rows(snap),
        extras=_cursor_extras(snap),
        fetched_at=snap.fetched_at,
        cursor=snap,
    )
