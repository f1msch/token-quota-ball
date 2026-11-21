"""调用 Cursor 用量接口，对齐官网 Spending / Included Usage。"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ...platform.timeutil import BEIJING_TZ as BJ
from .auth import CursorAuth, load_auth

logger = logging.getLogger(__name__)
API_BASE = "https://api2.cursor.sh"
CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
FIRST_PARTY_PREFIXES = ("composer-", "grok-", "cursor-grok-", "vega")
SAND_USAGE_PATH = "/aiserver.v1.DashboardService/GetSandUsageStatus"


@dataclass(frozen=True)
class ModelUsage:
    name: str
    tokens: int
    percent: float
    cents: float = 0.0


@dataclass(frozen=True)
class CreditBalance:
    remaining_cents: int
    total_cents: int
    used_cents: int
    expires_at: datetime | None = None

    @property
    def remaining_percent(self) -> float:
        if self.total_cents <= 0:
            return 0.0
        return self.remaining_cents / self.total_cents * 100


@dataclass(frozen=True)
class GrokBotUsage:
    """Grok Bot 周额度（Cursor 内部协议名 Sand）。"""

    usage_percent: float | None
    has_included_allowance: bool
    uses_pooled_enterprise: bool = False
    has_available_usage: bool | None = None
    period_start: datetime | None = None
    reset_at: datetime | None = None
    trial_expires_at: datetime | None = None
    plan_label: str | None = None
    is_unified: bool | None = None
    banked_reset_count: int = 0
    error: str | None = None

    @property
    def seconds_left(self) -> float | None:
        if not self.reset_at:
            return None
        return (self.reset_at - datetime.now(BJ)).total_seconds()

    @property
    def show_meter(self) -> bool:
        return self.has_included_allowance and self.usage_percent is not None and self.error is None


@dataclass(frozen=True)
class QuotaSnapshot:
    email: str | None
    plan_name: str
    membership: str | None
    price: str | None
    total_percent_used: float
    first_party_percent_used: float
    api_percent_used: float
    first_party_tokens: int
    api_tokens: int
    first_party_models: tuple[ModelUsage, ...] = ()
    api_models: tuple[ModelUsage, ...] = ()
    cycle_start: datetime | None = None
    cycle_end: datetime | None = None
    display_message: str | None = None
    credits: CreditBalance | None = None
    grok_bot: GrokBotUsage | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(BJ))

    @property
    def seconds_left(self) -> float | None:
        if not self.cycle_end:
            return None
        return (self.cycle_end - datetime.now(BJ)).total_seconds()

    @property
    def hit_limit(self) -> bool:
        msg = (self.display_message or "").lower()
        return (
            self.total_percent_used >= 99.5
            or self.first_party_percent_used >= 99.5
            or self.api_percent_used >= 99.5
            or "hit your usage limit" in msg
        )


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "1"}:
            return True
        if low in {"false", "0"}:
            return False
    return None


def _pick(body: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in body and body[key] is not None:
            return body[key]
    return None


def _ms_to_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).astimezone(BJ)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _parse_ts(value: Any) -> datetime | None:
    """解析 GetSandUsageStatus 的时间戳：ISO 8601 或纪元秒 / 毫秒。"""
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(BJ)
    if isinstance(value, (int, float)):
        return _epoch_to_dt(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _epoch_to_dt(float(text))
        except ValueError:
            pass
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(BJ)
    return None


def _epoch_to_dt(value: float) -> datetime | None:
    if not math.isfinite(value) or value <= 0:
        return None
    # 2026 年约为 1.79e9 秒 / 1.79e12 毫秒
    seconds = value / 1000 if value >= 1e12 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(BJ)
    except (OSError, OverflowError, ValueError):
        return None


def _post_json(path: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(body or {}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "User-Agent": "token-quota-ball/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {path} 失败 ({exc.code}): {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络错误: {exc.reason}") from exc


def refresh_access_token(refresh_token: str) -> str:
    req = urllib.request.Request(
        f"{API_BASE}/oauth/token",
        data=json.dumps(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("shouldLogout") or not data.get("access_token"):
        raise RuntimeError("登录已失效，请重新在 Cursor 中登录。")
    return data["access_token"]


def _row_tokens(row: dict[str, Any]) -> int:
    return sum(
        _as_int(row.get(k))
        for k in ("inputTokens", "outputTokens", "cacheWriteTokens", "cacheReadTokens")
    )


def _model_name(intent: str) -> str:
    return "auto" if intent in {"default", "auto"} else intent


def _is_first_party(intent: str, auto_bucket: set[str], api_percent: float) -> bool:
    if intent in {"default", "auto"} or intent in auto_bucket:
        return True
    lower = intent.lower()
    if any(lower.startswith(p) for p in FIRST_PARTY_PREFIXES):
        return True
    # API%=0 时，官网会把其余 included 模型也归进 First-Party
    return api_percent < 0.01


def _to_model_usages(
    rows: list[tuple[str, int, float]],
    pool: float,
    bucket_pct: float,
) -> list[ModelUsage]:
    result: list[ModelUsage] = []
    total = sum(t for _, t, _ in rows) or 1
    for name, tokens, cents in sorted(rows, key=lambda x: x[1], reverse=True):
        if pool > 0:
            pct = tokens / pool * 100
        elif bucket_pct > 0:
            pct = tokens / total * bucket_pct
        else:
            pct = 0.0
        result.append(ModelUsage(name=name, tokens=tokens, percent=pct, cents=cents))
    return result


def _build_model_rows(
    aggregations: list[dict[str, Any]],
    auto_bucket: set[str],
    first_party_pct: float,
    api_pct: float,
) -> tuple[list[ModelUsage], list[ModelUsage], int, int]:
    first_party: list[tuple[str, int, float]] = []
    api: list[tuple[str, int, float]] = []

    for row in aggregations:
        intent = str(row.get("modelIntent") or "unknown")
        item = (_model_name(intent), _row_tokens(row), _as_float(row.get("totalCents")))
        if _is_first_party(intent, auto_bucket, api_pct):
            first_party.append(item)
        else:
            api.append(item)

    fp_tokens = sum(t for _, t, _ in first_party)
    api_tokens = sum(t for _, t, _ in api)
    fp_pool = fp_tokens / (first_party_pct / 100) if first_party_pct > 0.01 and fp_tokens else 0
    api_pool = api_tokens / (api_pct / 100) if api_pct > 0.01 and api_tokens else 0

    return (
        _to_model_usages(first_party, fp_pool, first_party_pct),
        _to_model_usages(api, api_pool, api_pct),
        fp_tokens,
        api_tokens,
    )


def _fetch_credits(token: str) -> CreditBalance | None:
    remaining: int | None = None
    total: int | None = None
    used: int | None = None
    expires_at: datetime | None = None

    try:
        body = _post_json("/aiserver.v1.DashboardService/GetCreditGrantsBalance", token)
        if body.get("hasCreditGrants"):
            remaining = _as_int(body.get("creditBalanceCents"))
            total = _as_int(body.get("totalCents"))
            used = _as_int(body.get("usedCents"))
    except RuntimeError as exc:
        logger.warning("拉取 Credits 失败: %s", str(exc)[:200])

    try:
        status = _post_json(
            "/aiserver.v1.DashboardService/GetUsageLimitStatusAndActiveGrants", token
        )
        grants = list(status.get("activeGrants") or [])
        expire_times = [dt for g in grants if (dt := _ms_to_dt(g.get("expiresAtMs")))]
        if expire_times:
            expires_at = min(expire_times)
        if total is None and grants:
            remaining = sum(_as_int(g.get("remainingCents")) for g in grants)
            total = sum(_as_int(g.get("totalCents")) for g in grants)
            used = max(0, total - remaining)
    except RuntimeError as exc:
        logger.warning("拉取 Credits 到期日失败: %s", str(exc)[:200])

    if not total:
        return None
    if remaining is None:
        remaining = 0
    if used is None:
        used = max(0, total - remaining)
    return CreditBalance(
        remaining_cents=remaining,
        total_cents=total,
        used_cents=used,
        expires_at=expires_at,
    )


def _optional_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _parse_grok_bot(body: dict[str, Any]) -> GrokBotUsage:
    pooled = _as_bool(
        _pick(body, "usesPooledEnterpriseAllowance", "uses_pooled_enterprise_allowance")
    ) is True
    included_zero = _as_bool(_pick(body, "includedLimitZero", "included_limit_zero")) is True
    has_nonzero = _as_bool(
        _pick(body, "hasNonZeroIncludedLimit", "has_non_zero_included_limit")
    )
    usage_raw = _pick(body, "usagePercent", "usage_percent")
    usage_percent: float | None = None
    if usage_raw is not None:
        parsed = _as_float(usage_raw, default=float("nan"))
        if math.isfinite(parsed) and parsed >= 0:
            usage_percent = parsed

    has_allowance = (not pooled) and (not included_zero) and (has_nonzero is not False)
    if has_allowance and has_nonzero is None and usage_percent is None:
        has_allowance = False

    return GrokBotUsage(
        usage_percent=usage_percent,
        has_included_allowance=has_allowance,
        uses_pooled_enterprise=pooled,
        has_available_usage=_as_bool(
            _pick(body, "hasAvailableUsage", "has_available_usage")
        ),
        period_start=_parse_ts(_pick(body, "currentPeriodStart", "current_period_start")),
        reset_at=_parse_ts(_pick(body, "nextResetTimestampUtc", "next_reset_timestamp_utc")),
        trial_expires_at=_parse_ts(_pick(body, "sandTrialExpiresAt", "sand_trial_expires_at")),
        plan_label=_optional_text(
            _pick(body, "grokPlanLabel", "grok_plan_label"),
            _pick(body, "includedUsageSuperGrokPlan", "included_usage_super_grok_plan"),
            _pick(body, "cursorPlanName", "cursor_plan_name"),
        ),
        is_unified=_as_bool(_pick(body, "isUnified", "is_unified")),
        banked_reset_count=max(
            0,
            _as_int(_pick(body, "availableBankedResetCount", "available_banked_reset_count"), 0),
        ),
    )


def _fetch_grok_bot(token: str) -> GrokBotUsage:
    """拉取 Grok Bot 周额度；失败时返回带 error 的对象，不抛给主流程。"""
    try:
        body = _post_json(SAND_USAGE_PATH, token)
        if not isinstance(body, dict):
            raise RuntimeError("Grok Bot 用量响应格式无效")
        grok = _parse_grok_bot(body)
        reset_log = grok.reset_at.isoformat() if grok.reset_at else "none"
        if grok.show_meter:
            logger.info(
                "Grok Bot usage=%.1f%% reset=%s pooled=%s",
                grok.usage_percent or 0.0,
                reset_log,
                grok.uses_pooled_enterprise,
            )
        else:
            logger.info(
                "Grok Bot 无个人周额度条 pooled=%s allowance=%s reset=%s",
                grok.uses_pooled_enterprise,
                grok.has_included_allowance,
                reset_log,
            )
        return grok
    except RuntimeError as exc:
        err = str(exc)
        logger.warning("拉取 Grok Bot 用量失败: %s", err[:200])
        return GrokBotUsage(
            usage_percent=None,
            has_included_allowance=False,
            error=err,
        )


def fetch_quota(auth: CursorAuth | None = None) -> QuotaSnapshot:
    auth = auth or load_auth()
    token = auth.access_token

    try:
        usage = _post_json("/aiserver.v1.DashboardService/GetCurrentPeriodUsage", token)
    except RuntimeError:
        if not auth.refresh_token:
            raise
        token = refresh_access_token(auth.refresh_token)
        usage = _post_json("/aiserver.v1.DashboardService/GetCurrentPeriodUsage", token)

    plan_name = (auth.membership or "Unknown").title()
    price = None
    try:
        plan = _post_json("/aiserver.v1.DashboardService/GetPlanInfo", token)
        info = plan.get("planInfo") or {}
        plan_name = info.get("planName") or plan_name
        price = info.get("price")
    except RuntimeError:
        pass

    plan_usage = usage.get("planUsage") or {}
    auto_pct = _as_float(plan_usage.get("autoPercentUsed"))
    api_pct = _as_float(plan_usage.get("apiPercentUsed"))
    total_pct = _as_float(plan_usage.get("totalPercentUsed"))
    auto_bucket = {str(x) for x in (usage.get("autoBucketModels") or [])}

    aggregations: list[dict[str, Any]] = []
    try:
        agg = _post_json("/aiserver.v1.DashboardService/GetAggregatedUsageEvents", token)
        aggregations = list(agg.get("aggregations") or [])
    except RuntimeError:
        pass

    fp_models, api_models, fp_tokens, api_tokens = _build_model_rows(
        aggregations, auto_bucket, auto_pct, api_pct
    )

    credits = _fetch_credits(token)
    grok_bot = _fetch_grok_bot(token)

    snap = QuotaSnapshot(
        email=auth.email,
        plan_name=plan_name,
        membership=auth.membership,
        price=price,
        total_percent_used=total_pct,
        first_party_percent_used=auto_pct,
        api_percent_used=api_pct,
        first_party_tokens=fp_tokens,
        api_tokens=api_tokens,
        first_party_models=tuple(fp_models),
        api_models=tuple(api_models),
        cycle_start=_ms_to_dt(usage.get("billingCycleStart")),
        cycle_end=_ms_to_dt(usage.get("billingCycleEnd")),
        display_message=usage.get("autoModelSelectedDisplayMessage") or usage.get("displayMessage"),
        credits=credits,
        grok_bot=grok_bot,
        fetched_at=datetime.now(BJ),
    )
    credit_log = "none"
    if credits:
        credit_log = f"{credits.remaining_cents}/{credits.total_cents}c"
    logger.info(
        "用量 total=%.0f%% first-party=%.0f%% api=%.0f%% plan=%s credits=%s",
        snap.total_percent_used,
        snap.first_party_percent_used,
        snap.api_percent_used,
        snap.plan_name,
        credit_log,
    )
    return snap
