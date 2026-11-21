"""WorkBuddy billing usage: personal and enterprise credit meters."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from ...config import PROVIDER_META, load_workbuddy
from ...formatters import format_duration
from ...platform.logging_setup import now_beijing
from .._util import as_float, dig
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
from .session import _ms_to_dt, resolve_session

logger = logging.getLogger(__name__)

BILLING_HOST = "copilot.tencent.com"
BILLING_BASE = f"https://{BILLING_HOST}"
PERSONAL_PATH = "/v2/billing/meter/get-user-resource"
ENTERPRISE_PATH = "/v2/billing/meter/get-enterprise-user-usage"
UNCONFIG_NOTES = "请先登录本机 WorkBuddy 桌面端。"


def _package_status(item: dict[str, Any]) -> int | None:
    value = dig(item, "Status", "status", "State")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _package_metrics(item: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    limit = as_float(
        dig(
            item,
            "CycleCapacitySizePrecise",
            "CycleTotalCapacity",
            "CycleCapacitySize",
            "CapacitySizePrecise",
            "CapacitySize",
            "TotalCapacity",
            "limit",
            "Limit",
        )
    )
    remaining = as_float(
        dig(
            item,
            "CycleCapacityRemainPrecise",
            "CycleRemainCapacity",
            "CycleCapacityRemain",
            "CapacityRemainPrecise",
            "CapacityRemain",
            "RemainCapacity",
            "remaining",
            "Remaining",
        )
    )
    used = as_float(
        dig(
            item,
            "CycleCapacityUsedPrecise",
            "CycleUsedCapacity",
            "CycleCapacityUsed",
            "CapacityUsedPrecise",
            "CapacityUsed",
            "UsedCapacity",
            "used",
            "Used",
        )
    )
    return used, limit, remaining


def _iter_packages(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            # 自身像资源包
            if any(
                key in node
                for key in (
                    "CycleCapacitySizePrecise",
                    "CycleTotalCapacity",
                    "CycleCapacityRemainPrecise",
                    "CycleRemainCapacity",
                    "CapacityRemain",
                    "CycleCapacityUsedPrecise",
                )
            ):
                found.append(node)
            for key in (
                "Accounts",
                "accounts",
                "Packages",
                "packages",
                "Resources",
                "resources",
                "List",
                "list",
                "Data",
                "data",
                "Records",
                "records",
            ):
                if key in node:
                    walk(node[key], depth + 1)
            # 常见包裹层
            for key in ("Response", "result", "Result"):
                if key in node:
                    walk(node[key], depth + 1)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    walk(item, depth + 1)

    walk(payload)
    # 去重（按 id）
    unique: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in found:
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique


def _is_active_package(item: dict[str, Any], now: datetime) -> bool:
    status = _package_status(item)
    # 0=有效；3=已用尽仍可能残留 0 剩余。排除明确失效状态。
    if status is not None and status not in {0, "0"}:
        # 有些接口用 1 表示有效，保守：若还能读到剩余/上限则纳入，明确的过期/失效排除
        if status in {2, 4, 5}:
            return False
        if status == 3:
            used, limit, remaining = _package_metrics(item)
            if remaining is not None and remaining <= 0:
                return False
    end = _ms_to_dt(dig(item, "CycleEndTime", "PackageEndTime", "EndTime", "ExpireTime"))
    if end is not None and end < now - timedelta(minutes=1):
        return False
    return True


def _parse_personal(payload: Any) -> tuple[float, float, float, datetime | None, str]:
    now = now_beijing()
    packages = [item for item in _iter_packages(payload) if _is_active_package(item, now)]
    if not packages:
        # 若过滤后为空，尝试不过滤状态再算一次，避免因 Status 枚举差异丢光数据
        packages = _iter_packages(payload)
    used_sum = 0.0
    limit_sum = 0.0
    remain_sum = 0.0
    reset_at: datetime | None = None
    plan = ""
    counted = 0
    for item in packages:
        used, limit, remaining = _package_metrics(item)
        if used is None and limit is not None and remaining is not None:
            used = max(0.0, limit - remaining)
        if remaining is None and limit is not None and used is not None:
            remaining = max(0.0, limit - used)
        if limit is None and used is not None and remaining is not None:
            limit = used + remaining
        if limit is None and remaining is None and used is None:
            continue
        used_sum += used or 0.0
        limit_sum += limit or 0.0
        remain_sum += remaining if remaining is not None else 0.0
        counted += 1
        end = _ms_to_dt(dig(item, "CycleEndTime", "PackageEndTime", "EndTime", "ExpireTime"))
        if end and (reset_at is None or end < reset_at):
            reset_at = end
        plan_name = dig(item, "SubscriptionPackageName", "PackageName", "PlanName", "ProductName")
        if isinstance(plan_name, str) and plan_name.strip() and not plan:
            plan = plan_name.strip()
    if counted == 0:
        raise ValueError("接口未返回可识别的积分资源包")
    return used_sum, limit_sum, remain_sum, reset_at, plan


def _looks_unlimited(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"unlimited", "unlimit", "infinite", "无限", "-1"}:
        return True
    try:
        number = float(value)
        return number < 0
    except (TypeError, ValueError):
        return False


def _parse_enterprise(payload: Any) -> tuple[float | None, float | None, float | None, datetime | None, str, bool]:
    data = payload
    if isinstance(payload, dict):
        data = dig(payload, "data", "Data", "result", "Result", "Response") or payload
        if isinstance(data, dict) and isinstance(data.get("Data"), (dict, list)):
            data = data.get("Data")
    node = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data
    if not isinstance(node, dict):
        raise ValueError("企业额度响应无法解析")
    unlimited = any(
        _looks_unlimited(dig(node, key))
        for key in ("Unlimited", "unlimited", "IsUnlimited", "QuotaType", "LimitType")
    )
    used = as_float(dig(node, "Used", "used", "Usage", "TotalUsed", "CycleUsed"))
    limit = as_float(dig(node, "Limit", "limit", "Quota", "TotalQuota", "CycleQuota"))
    remaining = as_float(dig(node, "Remaining", "remaining", "Remain", "Left"))
    if _looks_unlimited(limit):
        unlimited = True
        limit = None
    reset_at = _ms_to_dt(dig(node, "ResetTime", "resetTime", "CycleEndTime", "ExpireTime"))
    plan = ""
    plan_val = dig(node, "PlanName", "PackageName", "SubscriptionPackageName", "Edition")
    if isinstance(plan_val, str):
        plan = plan_val.strip()
    if used is None and remaining is None and not unlimited:
        # 有的企业接口仍按资源包列表返回
        try:
            used, limit, remaining, reset_at, plan = _parse_personal(payload)
        except ValueError:
            raise ValueError("企业额度响应缺少已用/上限字段") from None
    return used, limit, remaining, reset_at, plan, unlimited


def _api_error_message(status: int, payload: Any, raw: str) -> str:
    if isinstance(payload, dict):
        for key in ("msg", "message", "Message", "error", "Error", "ErrorMsg"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return f"HTTP {status}: {value.strip()}" if status >= 400 else value.strip()
            if isinstance(value, dict):
                msg = value.get("Message") or value.get("message") or value.get("Code")
                if msg:
                    return str(msg)
        code = payload.get("code", payload.get("Code"))
        if code not in (None, 0, "0", "OK", "Success"):
            return f"接口错误 code={code}"
    if status >= 400:
        snippet = raw.strip().replace("\n", " ")[:180] or "无响应正文"
        return f"HTTP {status}: {snippet}"
    return f"无法解析响应（HTTP {status}）"


def _request(path: str, token: str, user_id: str) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "WorkBuddy/5.8.4",
        "Accept": "application/json",
    }
    if user_id:
        headers["X-User-Id"] = user_id
    body = json.dumps({"PageNumber": 1, "PageSize": 100}, ensure_ascii=False).encode("utf-8")
    status, payload, raw = http_json(
        BILLING_BASE + path,
        method="POST",
        headers=headers,
        body=body,
        allow_hosts=(BILLING_HOST,),
    )
    if isinstance(payload, dict):
        code = payload.get("code", payload.get("Code"))
        if code not in (None, 0, "0", "OK", "Success", 200, "200") or status >= 400:
            raise RuntimeError(_api_error_message(status, payload, raw))
        return payload
    if status >= 400 or payload is None:
        raise RuntimeError(_api_error_message(status, payload, raw))
    return payload


def fetch_workbuddy() -> ProviderSnapshot:
    cfg = load_workbuddy()
    token, user_id, source, blocked = resolve_session()
    if blocked:
        return unconfigured_snapshot("workbuddy", blocked, notes=UNCONFIG_NOTES)
    if not token:
        return unconfigured_snapshot(
            "workbuddy",
            "未登录桌面端",
            notes=UNCONFIG_NOTES,
        )

    account_type = cfg.account_type
    plan = ""
    reset_at: datetime | None = None
    used = limit = remaining = None
    unlimited = False
    mode = "personal"
    last_error = ""

    def try_personal() -> None:
        nonlocal used, limit, remaining, reset_at, plan, mode
        payload = _request(PERSONAL_PATH, token, user_id)
        used, limit, remaining, reset_at, plan = _parse_personal(payload)
        mode = "personal"

    def try_enterprise() -> None:
        nonlocal used, limit, remaining, reset_at, plan, mode, unlimited
        payload = _request(ENTERPRISE_PATH, token, user_id)
        used, limit, remaining, reset_at, plan, unlimited = _parse_enterprise(payload)
        mode = "enterprise"

    try:
        if account_type == "enterprise":
            try_enterprise()
        elif account_type == "personal":
            try_personal()
        else:
            try:
                try_personal()
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.info("WorkBuddy 个人额度不可用，尝试企业接口: %s", last_error)
                try_enterprise()
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "WorkBuddy 额度请求失败"
        if "401" in message or "403" in message or "Authorization" in message or "登录" in message:
            return error_snapshot("workbuddy", f"认证失败：{message}", notes="请重新登录本机 WorkBuddy 桌面端。")
        if last_error:
            message = f"{message}（个人接口：{last_error}）"
        return error_snapshot("workbuddy", message)

    if unlimited:
        display = "不限"
        pct = None
        value = "不限"
        remain_text = "企业账户为无限额度" if remaining is None else f"剩余 {format_number(remaining)}"
    else:
        if remaining is None and limit is not None and used is not None:
            remaining = max(0.0, limit - used)
        if used is None and limit is not None and remaining is not None:
            used = max(0.0, limit - remaining)
        pct = used_percent(used, limit, remaining)
        display = f"{pct:.0f}%" if pct is not None else "--"
        if remaining is not None and limit is not None:
            value = f"{format_number(remaining)} / {format_number(limit)}"
        elif remaining is not None:
            value = f"剩余 {format_number(remaining)}"
        elif used is not None and limit is not None:
            value = f"已用 {format_number(used)} / {format_number(limit)}"
        else:
            value = display
        remain_text = value

    extras = []
    if reset_at:
        left = (reset_at - now_beijing()).total_seconds()
        extras.append(f"重置 {reset_at.strftime('%m-%d %H:%M')}（剩余 {format_duration(left)}）")
    extras.append("个人账户" if mode == "personal" else "企业账户")

    rows = (
        MeterRow(
            "credits",
            "积分",
            remain_text if not unlimited else "不限",
            pct,
            meter_color(pct) if not unlimited else "#5a6a7a",
            detail="",
        ),
    )
    logger.info(
        "WorkBuddy 用量 mode=%s used=%s limit=%s remaining=%s source=%s",
        mode,
        used,
        limit,
        remaining,
        "config" if source == "config" else "local-file-or-unknown",
    )
    meta = PROVIDER_META["workbuddy"]
    return ProviderSnapshot(
        provider_id="workbuddy",
        title=meta["title"],
        account=user_id,
        plan=plan or ("企业套餐" if mode == "enterprise" else "个人套餐"),
        display_text=display,
        percent_used=pct,
        rows=rows,
        extras=tuple(extras),
        notes="",
    )
