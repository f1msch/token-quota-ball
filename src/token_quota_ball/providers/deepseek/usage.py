"""DeepSeek 官方账户余额。

官方文档：GET https://api.deepseek.com/user/balance
鉴权：Authorization: Bearer <API Key>

该接口只返回余额（total / granted / topped_up），没有会话或周期额度分母，
因此默认不把水位伪装成百分比。若在设置里填写了参考额度，则用水位表示已用占比。
"""

from __future__ import annotations

import logging
from typing import Any

from ...config import PROVIDER_META, load_deepseek
from ..http import http_json
from ..models import (
    MeterRow,
    ProviderSnapshot,
    error_snapshot,
    format_number,
    meter_color,
    unconfigured_snapshot,
)

logger = logging.getLogger(__name__)

API_HOST = "api.deepseek.com"
API_URL = "https://api.deepseek.com/user/balance"
UNCONFIG_NOTES = (
    "请在右键「提供方设置」填写 DeepSeek API Key，或设置环境变量 DEEPSEEK_API_KEY。"
    "可在 https://platform.deepseek.com 创建密钥。"
    "官方余额接口没有额度上限，水位需要自行填写参考额度才会显示。"
)


def _symbol(currency: str) -> str:
    cur = (currency or "").upper()
    if cur == "CNY":
        return "¥"
    if cur == "USD":
        return "$"
    return f"{cur} " if cur else ""


def _pick_balance(infos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not infos:
        return None
    for pref in ("CNY", "USD"):
        for item in infos:
            if str(item.get("currency") or "").upper() == pref:
                return item
    return infos[0]


def _amount(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _compact_money(symbol: str, value: float) -> str:
    if abs(value) >= 100:
        body = f"{value:.0f}"
    elif abs(value) >= 10:
        body = f"{value:.1f}".rstrip("0").rstrip(".")
    else:
        body = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{symbol}{body}"


def fetch_deepseek() -> ProviderSnapshot:
    cfg = load_deepseek()
    if not cfg.configured:
        return unconfigured_snapshot(
            "deepseek",
            "未配置 DeepSeek API Key，无法查询余额。",
            notes=UNCONFIG_NOTES,
        )
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Accept": "application/json",
    }
    try:
        status, payload, raw = http_json(
            API_URL,
            method="GET",
            headers=headers,
            allow_hosts=(API_HOST,),
        )
    except Exception as exc:  # noqa: BLE001
        return error_snapshot("deepseek", str(exc) or "请求失败", notes=UNCONFIG_NOTES)

    if not isinstance(payload, dict):
        snippet = (raw or "").strip().replace("\n", " ")[:180] or "无响应正文"
        return error_snapshot("deepseek", f"HTTP {status}: {snippet}", notes=UNCONFIG_NOTES)
    if status in {401, 403}:
        return error_snapshot("deepseek", "API Key 无效或已失效，请在「提供方设置」中更新。", notes=UNCONFIG_NOTES)
    if status >= 400:
        msg = payload.get("error") or payload.get("message") or payload.get("msg") or f"HTTP {status}"
        if isinstance(msg, dict):
            msg = msg.get("message") or msg.get("Message") or str(msg)
        return error_snapshot("deepseek", str(msg), notes=UNCONFIG_NOTES)

    infos = payload.get("balance_infos") or payload.get("balanceInfos") or []
    if not isinstance(infos, list):
        infos = []
    items = [item for item in infos if isinstance(item, dict)]
    chosen = _pick_balance(items)
    if chosen is None:
        return error_snapshot("deepseek", "余额接口未返回 balance_infos")

    currency = str(chosen.get("currency") or "")
    symbol = _symbol(currency)
    total = _amount(chosen, "total_balance", "totalBalance") or 0.0
    granted = _amount(chosen, "granted_balance", "grantedBalance")
    topped = _amount(chosen, "topped_up_balance", "toppedUpBalance")
    available = payload.get("is_available")

    pct: float | None = None
    notes = "官方接口只返回余额，没有周期额度上限。"
    if total <= 0:
        pct = 100.0
        display = _compact_money(symbol, 0.0)
        notes += "当前余额为 0，水位按用尽显示。"
    elif cfg.reference_balance is not None and cfg.reference_balance > 0:
        used = max(0.0, cfg.reference_balance - total)
        pct = max(0.0, min(100.0, used / cfg.reference_balance * 100.0))
        display = _compact_money(symbol, total)
        notes += f"水位按参考额度 {format_number(cfg.reference_balance)} 计算已用占比。"
    else:
        display = _compact_money(symbol, total)
        notes += "可在设置里填写参考额度后再显示水位。"

    rows = [
        MeterRow("total", "总余额", f"{symbol}{format_number(total)}", pct if cfg.reference_balance or total <= 0 else None, meter_color(pct if pct is not None else None)),
    ]
    if topped is not None:
        rows.append(MeterRow("topped", "充值余额", f"{symbol}{format_number(topped)}", None, "#e0b050"))
    if granted is not None:
        rows.append(MeterRow("granted", "赠送余额", f"{symbol}{format_number(granted)}", None, "#3ecfcf"))
    if cfg.reference_balance:
        rows.append(
            MeterRow(
                "ref",
                "参考额度",
                f"{symbol}{format_number(cfg.reference_balance)}",
                pct,
                meter_color(pct),
                "仅用于水位，不是官方额度上限",
            )
        )

    extras = [f"币种 {currency or '未知'}"]
    if available is False:
        extras.append("当前余额不可用于 API 调用")
    elif available is True:
        extras.append("可用于 API 调用")

    meta = PROVIDER_META["deepseek"]
    logger.info("DeepSeek 余额 currency=%s total=%s available=%s", currency, total, available)
    return ProviderSnapshot(
        provider_id="deepseek",
        title=meta["title"],
        account=currency,
        plan="API 余额",
        display_text=display,
        percent_used=pct,
        rows=tuple(rows),
        extras=tuple(extras),
        notes=notes,
    )
