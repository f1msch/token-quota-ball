"""JSON views of provider snapshots. Never includes secrets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from token_quota_ball.formatters import format_duration, format_tokens_cn, format_usd_cents
from token_quota_ball.providers.models import MeterRow, ProviderSnapshot


def reset_fact(view: ProviderSnapshot) -> str:
    """Pick the single reset/cycle-remaining fact, ignoring '更新于' and notes."""
    for extra in view.extras:
        text = extra.strip()
        if not text or text.startswith("更新于"):
            continue
        if text.startswith(("重置", "周期剩余", "该窗口重置", "Grok 剩余")) or "重置" in text:
            return text
    return ""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _meter(row: MeterRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "title": row.title,
        "value": row.value,
        "percent": row.percent,
        "color": row.color,
        "detail": row.detail,
    }


def _models(rows: tuple) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "tokens": item.tokens,
            "tokens_text": format_tokens_cn(item.tokens),
            "percent": item.percent,
            "cents": item.cents,
        }
        for item in rows
    ]


def _cursor(view: ProviderSnapshot) -> dict[str, Any] | None:
    snap = view.cursor
    if snap is None:
        return None
    credits = None
    if snap.credits is not None and snap.credits.total_cents > 0:
        c = snap.credits
        credits = {
            "remaining_cents": c.remaining_cents,
            "total_cents": c.total_cents,
            "used_cents": c.used_cents,
            "remaining_percent": c.remaining_percent,
            "remaining_text": format_usd_cents(c.remaining_cents),
            "total_text": format_usd_cents(c.total_cents),
            "expires_at": _iso(c.expires_at),
        }
    grok = None
    if snap.grok_bot is not None:
        g = snap.grok_bot
        grok = {
            "usage_percent": g.usage_percent,
            "has_included_allowance": g.has_included_allowance,
            "uses_pooled_enterprise": g.uses_pooled_enterprise,
            "has_available_usage": g.has_available_usage,
            "period_start": _iso(g.period_start),
            "reset_at": _iso(g.reset_at),
            "trial_expires_at": _iso(g.trial_expires_at),
            "plan_label": g.plan_label,
            "is_unified": g.is_unified,
            "banked_reset_count": g.banked_reset_count,
            "error": g.error,
            "show_meter": g.show_meter,
            "seconds_left": g.seconds_left,
        }
    return {
        "email": snap.email,
        "plan_name": snap.plan_name,
        "membership": snap.membership,
        "price": snap.price,
        "total_percent_used": snap.total_percent_used,
        "first_party_percent_used": snap.first_party_percent_used,
        "api_percent_used": snap.api_percent_used,
        "first_party_tokens": snap.first_party_tokens,
        "first_party_tokens_text": format_tokens_cn(snap.first_party_tokens),
        "api_tokens": snap.api_tokens,
        "api_tokens_text": format_tokens_cn(snap.api_tokens),
        "first_party_models": _models(snap.first_party_models),
        "api_models": _models(snap.api_models),
        "cycle_start": _iso(snap.cycle_start),
        "cycle_end": _iso(snap.cycle_end),
        "seconds_left": snap.seconds_left,
        "seconds_left_text": (
            f"周期剩余 {format_duration(snap.seconds_left)}" if snap.cycle_end else ""
        ),
        "display_message": snap.display_message,
        "hit_limit": snap.hit_limit,
        "credits": credits,
        "grok_bot": grok,
    }


def snapshot_dict(view: ProviderSnapshot | None, error: str | None = None) -> dict[str, Any]:
    if view is None:
        return {
            "provider_id": "",
            "title": "用量",
            "account": "",
            "plan": "",
            "subtitle": "",
            "display_text": "--",
            "percent_used": None,
            "status": "error",
            "error": error or "暂无数据",
            "ok": False,
            "rows": [],
            "extras": [],
            "notes": "",
            "fetched_at": None,
            "reset_fact": "",
            "cursor": None,
        }
    err = error or view.error
    return {
        "provider_id": view.provider_id,
        "title": view.title,
        "account": view.account,
        "plan": view.plan,
        "subtitle": view.subtitle,
        "display_text": view.display_text,
        "percent_used": view.percent_used,
        "status": view.status,
        "error": err,
        "ok": bool(view.ok and not error),
        "rows": [_meter(row) for row in view.rows],
        "extras": list(view.extras),
        "notes": view.notes,
        "fetched_at": _iso(view.fetched_at),
        "reset_fact": reset_fact(view),
        "cursor": _cursor(view),
    }
