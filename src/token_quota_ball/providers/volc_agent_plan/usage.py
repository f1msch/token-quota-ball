"""火山方舟 Agent Plan（AFP）额度查询。

依据官方文档：
https://ark.volcengine.com/region:cn-beijing/docs/get-afp-usage-api
https://ark.volcengine.com/region:cn-beijing/docs/get-seat-afp-usage-api

这是火山引擎「火山方舟」的 Agent Plan 套餐（单位 AFP），不是 Trae，也不是豆包 App。
鉴权必须使用 IAM Access Key（AK/SK）做火山引擎 V4 签名，不能用模型推理 API Key。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ...config import PROVIDER_META, load_volc_agent_plan
from ...platform.timeutil import BEIJING_TZ as BJ
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
from .signing import HOST, sign_headers

logger = logging.getLogger(__name__)

VERSION = "2024-01-01"
WINDOWS = (
    ("AFPFiveHour", "近 5 小时"),
    ("AFPDaily", "近 1 天"),
    ("AFPWeekly", "近 1 周"),
    ("AFPMonthly", "近 1 月"),
)
PLAN_LABELS = {"Small": "小规格", "Medium": "中规格", "Large": "大规格", "Max": "最大规格"}
UNCONFIG_NOTES = (
    "请在右键「提供方设置」填写火山引擎 IAM Access Key ID 与 Secret Access Key"
    "（控制台：访问控制 IAM → 访问密钥），不是方舟模型 API Key。"
    "也可使用环境变量 VOLC_ACCESSKEY / VOLC_SECRETKEY。"
    "企业版还需填写席位 ID（SeatIDs）。"
)

def _ms_to_dt(value: Any) -> datetime | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 1e12:
        number /= 1000.0
    return datetime.fromtimestamp(number, BJ)


def _window(data: dict[str, Any], key: str) -> tuple[float | None, float | None, datetime | None]:
    node = data.get(key)
    if not isinstance(node, dict):
        return None, None, None
    used = None
    quota = None
    try:
        used = float(node.get("Used"))
    except (TypeError, ValueError):
        used = None
    try:
        quota = float(node.get("Quota"))
    except (TypeError, ValueError):
        quota = None
    reset = _ms_to_dt(node.get("ResetTime"))
    return used, quota, reset


def _plan_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return PLAN_LABELS.get(text, text)


def _metadata_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("ResponseMetadata") or payload.get("ResponseMetaData") or {}
    if not isinstance(meta, dict):
        return None
    err = meta.get("Error")
    if not err:
        return None
    if isinstance(err, dict):
        code = err.get("Code") or err.get("code") or ""
        msg = err.get("Message") or err.get("message") or ""
        return f"{code}: {msg}".strip(": ")
    return str(err)


def _call_open(action: str, body_obj: dict[str, Any]) -> dict[str, Any]:
    cfg = load_volc_agent_plan()
    body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    # 官方示例 body 为 "{}"，保留紧凑 JSON，避免空白影响签名。
    if body_obj == {}:
        body = "{}"
    query = {"Action": action, "Version": VERSION}
    headers = sign_headers(
        access_key=cfg.access_key_id,
        secret_key=cfg.secret_access_key,
        session_token=cfg.session_token,
        method="POST",
        query=query,
        body=body,
    )
    url = f"https://{HOST}/?Action={action}&Version={VERSION}"
    status, payload, raw = http_json(
        url,
        method="POST",
        headers=headers,
        body=body.encode("utf-8"),
        allow_hosts=(HOST,),
    )
    if not isinstance(payload, dict):
        snippet = (raw or "").strip().replace("\n", " ")[:180] or "无响应正文"
        raise RuntimeError(f"HTTP {status}: {snippet}")
    err = _metadata_error(payload)
    if err:
        raise RuntimeError(err)
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")
    result = payload.get("Result")
    if not isinstance(result, dict):
        raise RuntimeError("响应缺少 Result")
    return result


def _rows_from_plan(data: dict[str, Any], prefix: str = "") -> tuple[list[MeterRow], float | None, str, datetime | None]:
    rows: list[MeterRow] = []
    tightest: tuple[float, str, datetime | None] | None = None
    for key, title in WINDOWS:
        used, quota, reset = _window(data, key)
        pct = used_percent(used, quota)
        if used is None and quota is None:
            continue
        reset_text = ""
        if reset:
            reset_text = f"重置 {reset.strftime('%m-%d %H:%M')}（剩余 {format_duration((reset - now_beijing()).total_seconds())}）"
        if used is not None and quota is not None:
            value = f"{format_number(used)} / {format_number(quota)} AFP"
        elif used is not None:
            value = f"已用 {format_number(used)} AFP"
        else:
            value = "--"
        if pct is not None:
            value = f"{pct:.0f}%  {value}"
        label = f"{prefix}{title}" if prefix else title
        rows.append(MeterRow(key if not prefix else f"{prefix}{key}", label, value, pct, meter_color(pct), reset_text))
        if pct is not None and (tightest is None or pct >= tightest[0]):
            tightest = (pct, label, reset)
    primary_pct = tightest[0] if tightest else None
    primary_label = tightest[1] if tightest else ""
    primary_reset = tightest[2] if tightest else None
    return rows, primary_pct, primary_label, primary_reset


def _fetch_personal() -> ProviderSnapshot:
    result = _call_open("GetAFPUsage", {})
    rows, pct, tight_label, reset = _rows_from_plan(result)
    if not rows:
        raise RuntimeError("个人版 Agent Plan 未返回窗口额度，请确认已订阅该套餐")
    plan = _plan_label(result.get("PlanType"))
    extras = []
    if reset:
        extras.append(f"该窗口重置剩余 {format_duration((reset - now_beijing()).total_seconds())}")
    meta = PROVIDER_META["volc_agent_plan"]
    display = f"{pct:.0f}%" if pct is not None else "--"
    return ProviderSnapshot(
        provider_id="volc_agent_plan",
        title=meta["title"],
        account="个人版",
        plan=f"Agent Plan {plan}".strip(),
        display_text=display,
        percent_used=pct,
        rows=tuple(rows),
        extras=tuple(extras),
        notes="",
    )


def _fetch_enterprise() -> ProviderSnapshot:
    cfg = load_volc_agent_plan()
    if not cfg.seat_ids:
        return unconfigured_snapshot(
            "volc_agent_plan",
            "企业版需要填写席位 ID（SeatIDs）才能查询 GetSeatAFPUsage。",
            notes=UNCONFIG_NOTES,
        )
    result = _call_open("GetSeatAFPUsage", {"SeatIDs": list(cfg.seat_ids)})
    usages = result.get("SeatAFPUsages")
    if not isinstance(usages, list) or not usages:
        raise RuntimeError("企业版未返回席位用量，请核对席位 ID")
    all_rows: list[MeterRow] = []
    tightest: tuple[float, str, datetime | None] | None = None
    plans: list[str] = []
    for item in usages:
        if not isinstance(item, dict):
            continue
        seat = str(item.get("SeatID") or item.get("SeatId") or "").strip() or "席位"
        plan = _plan_label(item.get("PlanType"))
        if plan:
            plans.append(f"{seat} {plan}")
        prefix = f"{seat} · " if len(usages) > 1 else ""
        rows, pct, label, reset = _rows_from_plan(item, prefix=prefix)
        all_rows.extend(rows)
        if pct is not None and (tightest is None or pct >= tightest[0]):
            tightest = (pct, label, reset)
    if not all_rows:
        raise RuntimeError("企业版席位用量无法解析")
    pct = tightest[0] if tightest else None
    extras = []
    if tightest:
        if tightest[2]:
            extras.append(f"该窗口重置剩余 {format_duration((tightest[2] - now_beijing()).total_seconds())}")
    meta = PROVIDER_META["volc_agent_plan"]
    return ProviderSnapshot(
        provider_id="volc_agent_plan",
        title=meta["title"],
        account="企业版",
        plan="、".join(plans) or "Agent Plan 企业版",
        display_text=f"{pct:.0f}%" if pct is not None else "--",
        percent_used=pct,
        rows=tuple(all_rows),
        extras=tuple(extras),
        notes="",
    )


def fetch_volc_agent_plan() -> ProviderSnapshot:
    cfg = load_volc_agent_plan()
    if not cfg.configured:
        return unconfigured_snapshot(
            "volc_agent_plan",
            "未配置火山引擎 Access Key，无法查询 Agent Plan 额度。",
            notes=UNCONFIG_NOTES,
        )
    try:
        if cfg.account_type == "enterprise":
            return _fetch_enterprise()
        return _fetch_personal()
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "火山 Agent Plan 查询失败"
        lower = message.lower()
        if "signature" in lower or "invalidaccesskey" in lower or "auth" in lower or "forbidden" in lower:
            return error_snapshot("volc_agent_plan", f"鉴权失败：{message}", notes=UNCONFIG_NOTES)
        return error_snapshot("volc_agent_plan", message, notes=UNCONFIG_NOTES)
