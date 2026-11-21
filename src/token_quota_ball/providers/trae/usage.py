"""Trae CN 账号额度：沿用本机 IDE 登录态查询积分用量。

额度接口（IDE 内部调用）::

    POST https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage
    Authorization: Cloud-IDE-JWT <token>
    {"require_usage": true, "req_source": 1}

返回 ``usage_summary``（已用积分 / 总额度 / 已用比例）、``total_balance``
以及按资源包拆分的 ``user_entitlement_pack_list``。水位取 ``consumption_ratio``。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from ...config import PROVIDER_META
from ...platform.timeutil import BEIJING_TZ as BJ
from .._util import as_float, dig
from ...formatters import format_duration
from ...platform.logging_setup import now_beijing
from ..http import http_json
from ..models import (
    MeterRow,
    ProviderSnapshot,
    error_snapshot,
    format_number,
    meter_color,
    unconfigured_snapshot,
    used_percent,
)
from .session import DEFAULT_HOST, resolve_session

logger = logging.getLogger(__name__)

USAGE_PATH = "/trae/api/v2/pay/ide_user_ent_usage"
ALLOWED_HOSTS = ("api.trae.cn", "api.trae.com.cn", "api.trae.ai")
UNCONFIG_NOTES = (
    "请先登录本机 Trae CN（Trae IDE）。额度自动读取自本机登录态，无需在设置里填写。"
)


def _safe_host(host: str) -> str:
    parsed = urlparse(host or "")
    name = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and name in ALLOWED_HOSTS:
        return f"https://{name}"
    return DEFAULT_HOST


def _unix_to_dt(value: Any) -> datetime | None:
    number = as_float(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, BJ)


def _packs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("user_entitlement_pack_list")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _pack_metrics(pack: dict[str, Any]) -> tuple[float | None, float | None, datetime | None]:
    base = pack.get("entitlement_base_info") if isinstance(pack.get("entitlement_base_info"), dict) else {}
    quota = base.get("quota") if isinstance(base.get("quota"), dict) else {}
    usage = pack.get("usage") if isinstance(pack.get("usage"), dict) else {}
    limit = as_float(dig(quota, "credits_limit", "creditsLimit"))
    used = as_float(dig(usage, "credits_amount", "creditsAmount"))
    end = _unix_to_dt(dig(base, "end_time", "endTime"))
    return used, limit, end


def _api_error(status: int, payload: Any, raw: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "msg", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        code = payload.get("code")
        if code not in (None, 0, "0"):
            return f"接口错误 code={code}"
    if status >= 400:
        snippet = (raw or "").strip().replace("\n", " ")[:180] or "无响应正文"
        return f"HTTP {status}: {snippet}"
    return f"无法解析响应（HTTP {status}）"


def fetch_trae() -> ProviderSnapshot:
    session, session_error = resolve_session()
    if session_error:
        return error_snapshot("trae", f"读取本机 Trae 登录态失败：{session_error}", notes=UNCONFIG_NOTES)
    if session is None:
        return unconfigured_snapshot("trae", "未登录本机 Trae CN", notes=UNCONFIG_NOTES)

    host = _safe_host(session.host)
    url = host + USAGE_PATH
    headers = {
        "Authorization": f"Cloud-IDE-JWT {session.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = b'{"require_usage":true,"req_source":1}'
    try:
        status, payload, raw = http_json(
            url,
            method="POST",
            headers=headers,
            body=body,
            allow_hosts=ALLOWED_HOSTS,
        )
    except Exception as exc:  # noqa: BLE001
        return error_snapshot("trae", str(exc) or "Trae 额度请求失败", notes=UNCONFIG_NOTES)

    if not isinstance(payload, dict):
        return error_snapshot("trae", _api_error(status, payload, raw), notes=UNCONFIG_NOTES)
    if status in {401, 403}:
        return error_snapshot("trae", "Trae 登录态已失效，请重新登录本机 Trae CN。", notes=UNCONFIG_NOTES)
    code = payload.get("code")
    if code not in (None, 0, "0") or status >= 400:
        return error_snapshot("trae", _api_error(status, payload, raw), notes=UNCONFIG_NOTES)

    summary = payload.get("usage_summary") if isinstance(payload.get("usage_summary"), dict) else {}
    used = as_float(dig(summary, "consumed_amount", "consumedAmount"))
    limit = as_float(dig(summary, "total_amount", "totalAmount"))
    ratio = as_float(dig(summary, "consumption_ratio", "consumptionRatio"))
    balance = as_float(dig(payload, "total_balance", "totalBalance"))

    packs = _packs(payload)
    grouped: dict[str, dict[str, Any]] = {}
    reset_at: datetime | None = None
    now = now_beijing()
    for pack in packs:
        pack_used, pack_limit, end = _pack_metrics(pack)
        if not pack_limit:
            continue
        title = str(
            dig(pack, "group_name", "groupName")
            or dig(pack, "display_desc", "displayDesc")
            or "额度包"
        ).strip()
        slot = grouped.setdefault(title, {"used": 0.0, "limit": 0.0, "end": None})
        slot["used"] += pack_used or 0.0
        slot["limit"] += pack_limit or 0.0
        if end is not None:
            if slot["end"] is None or end < slot["end"]:
                slot["end"] = end
            if pack_limit and end >= now and (reset_at is None or end < reset_at):
                reset_at = end

    if limit is None or limit <= 0:
        limit = sum(item["limit"] for item in grouped.values()) or None
    if used is None:
        used = sum(item["used"] for item in grouped.values()) or None
    if ratio is not None:
        pct = max(0.0, min(100.0, ratio * 100.0))
    else:
        pct = used_percent(used, limit, balance)

    if pct is not None:
        display = f"{pct:.0f}%"
    elif balance is not None:
        display = format_number(balance)
    else:
        display = "--"

    rows: list[MeterRow] = []
    if used is not None and limit is not None:
        rows.append(
            MeterRow("credits", "积分", f"{format_number(used)} / {format_number(limit)}", pct, meter_color(pct))
        )
    elif limit is not None:
        rows.append(MeterRow("credits", "积分上限", format_number(limit), pct, meter_color(pct)))
    if balance is not None:
        rows.append(MeterRow("balance", "剩余积分", format_number(balance), None, "#3ecfcf"))

    for title, item in grouped.items():
        pack_limit = item["limit"] or None
        pack_used = item["used"]
        pack_pct = used_percent(pack_used, pack_limit)
        rows.append(
            MeterRow(
                f"pack:{title}",
                title,
                f"已用 {format_number(pack_used)} / {format_number(pack_limit)}" if pack_limit else "—",
                pack_pct,
                meter_color(pack_pct),
                item["end"].strftime("%m-%d %H:%M 到期") if item["end"] else "",
            )
        )

    extras: list[str] = []
    if reset_at is not None:
        left = (reset_at - now).total_seconds()
        extras.append(f"重置 {reset_at.strftime('%m-%d %H:%M')}（剩余 {format_duration(left)}）")
    if session.region:
        extras.append(f"区域 {session.region}")

    meta = PROVIDER_META["trae"]
    logger.info(
        "Trae 额度 used=%s limit=%s balance=%s packs=%s",
        used,
        limit,
        balance,
        len(grouped),
    )
    return ProviderSnapshot(
        provider_id="trae",
        title=meta["title"],
        account=session.username or session.user_id,
        plan="积分额度",
        display_text=display,
        percent_used=pct,
        rows=tuple(rows),
        extras=tuple(extras),
        notes="数据来自本机 Trae CN 登录态（ide_user_ent_usage），单位是积分。",
    )
