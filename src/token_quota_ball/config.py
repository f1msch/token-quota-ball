"""本机提供方配置：密钥只保存在本地文件或环境变量，不会被打印。"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .platform.paths import CONFIG_DIR, CONFIG_PATH

logger = logging.getLogger(__name__)

PROVIDER_IDS = ("cursor", "workbuddy", "volc_agent_plan", "deepseek", "trae")

PROVIDER_META = {
    # title is the official full name used on the ball, menus, and details.
    "cursor": {"title": "Cursor"},
    "workbuddy": {"title": "WorkBuddy"},
    "volc_agent_plan": {"title": "火山方舟 Agent Plan"},
    "deepseek": {"title": "DeepSeek"},
    "trae": {"title": "Trae"},
}

# In-memory overlay for connection tests; never written to disk by itself.
_overlay_lock = threading.RLock()
_CONFIG_OVERLAY: dict[str, Any] | None = None


def config_path() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_PATH


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _merge_dict(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            merged = dict(data[key])
            merged.update(value)
            data[key] = merged
        else:
            data[key] = value
    return data


def load_raw() -> dict[str, Any]:
    with _overlay_lock:
        if _CONFIG_OVERLAY is not None:
            return copy.deepcopy(_CONFIG_OVERLAY)
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取提供方配置失败: %s", exc)
        return {}


def save_raw(update: dict[str, Any]) -> Path:
    """合并写入配置。只更新提供的键，不在日志里输出密钥。"""
    with _overlay_lock:
        # Always merge against the on-disk file, not a test overlay.
        path = config_path()
        disk: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disk = loaded
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取提供方配置失败: %s", exc)
        data = _merge_dict(disk, update)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("已保存提供方配置到 %s", path)
        return path


@contextmanager
def temporary_config_overlay(update: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Apply a config overlay in-memory for connection tests (no disk write)."""
    global _CONFIG_OVERLAY
    path = config_path()
    disk: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                disk = loaded
        except (OSError, json.JSONDecodeError):
            disk = {}
    merged = _merge_dict(disk, update)
    with _overlay_lock:
        previous = _CONFIG_OVERLAY
        _CONFIG_OVERLAY = merged
    try:
        yield copy.deepcopy(merged)
    finally:
        with _overlay_lock:
            _CONFIG_OVERLAY = previous


def _pick_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pick_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


@dataclass(frozen=True)
class WorkBuddyConfig:
    access_token: str = ""
    user_id: str = ""
    auth_file: str = ""
    account_type: str = "auto"  # auto | personal | enterprise
    app_path: str = ""


@dataclass(frozen=True)
class VolcAgentPlanConfig:
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    account_type: str = "personal"  # personal | enterprise
    seat_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key)


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str = ""
    reference_balance: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class TraeConfig:
    data_dir: str = ""
    token: str = ""
    host: str = ""
    user_id: str = ""


def load_workbuddy() -> WorkBuddyConfig:
    """WorkBuddy uses the local desktop session automatically.

    Settings UI does not collect credentials. An optional override is honored
    only when the matching environment variable is already set.
    """
    account_type = _pick_str(_pick_env("WORKBUDDY_ACCOUNT_TYPE"), "auto").lower()
    if account_type not in {"auto", "personal", "enterprise"}:
        account_type = "auto"
    return WorkBuddyConfig(
        access_token=_pick_env("WORKBUDDY_ACCESS_TOKEN", "WORKBUDDY_TOKEN"),
        user_id=_pick_env("WORKBUDDY_USER_ID"),
        auth_file=_pick_env("WORKBUDDY_AUTH_FILE"),
        account_type=account_type,
        app_path=_pick_env("WORKBUDDY_APP_EXECUTABLE", "WORKBUDDY_ELECTRON_BIN"),
    )


def load_volc_agent_plan() -> VolcAgentPlanConfig:
    raw = _as_dict(load_raw().get("volc_agent_plan"))
    account_type = _pick_str(raw.get("account_type"), "personal").lower()
    if account_type not in {"personal", "enterprise"}:
        account_type = "personal"
    seats_raw = raw.get("seat_ids") or raw.get("seatIds") or _pick_env("VOLC_SEAT_IDS")
    seats: list[str] = []
    if isinstance(seats_raw, str):
        seats = [part.strip() for part in seats_raw.replace(";", ",").split(",") if part.strip()]
    elif isinstance(seats_raw, (list, tuple)):
        seats = [str(part).strip() for part in seats_raw if str(part).strip()]
    return VolcAgentPlanConfig(
        access_key_id=_pick_str(
            raw.get("access_key_id"),
            raw.get("accessKeyId"),
            _pick_env("VOLC_ACCESSKEY", "VOLC_ACCESS_KEY_ID", "VOLCENGINE_ACCESS_KEY", "VOLC_AK"),
        ),
        secret_access_key=_pick_str(
            raw.get("secret_access_key"),
            raw.get("secretAccessKey"),
            _pick_env("VOLC_SECRETKEY", "VOLC_SECRET_ACCESS_KEY", "VOLCENGINE_SECRET_KEY", "VOLC_SK"),
        ),
        session_token=_pick_str(
            raw.get("session_token"),
            raw.get("sessionToken"),
            _pick_env("VOLC_SESSION_TOKEN", "VOLCENGINE_SESSION_TOKEN"),
        ),
        account_type=account_type,
        seat_ids=tuple(seats),
    )


def load_trae() -> TraeConfig:
    """Trae CN 默认读取本机 IDE 登录态，设置页不收集密钥。

    可用环境变量覆盖：TRAE_CN_USER_DATA（用户目录）、TRAE_CLOUDIDE_TOKEN、
    TRAE_API_HOST、TRAE_USER_ID。
    """
    raw = _as_dict(load_raw().get("trae"))
    return TraeConfig(
        data_dir=_pick_str(raw.get("data_dir"), raw.get("dataDir"), _pick_env("TRAE_CN_USER_DATA", "TRAE_USER_DATA")),
        token=_pick_str(raw.get("token"), _pick_env("TRAE_CLOUDIDE_TOKEN", "TRAE_TOKEN")),
        host=_pick_str(raw.get("host"), _pick_env("TRAE_API_HOST")),
        user_id=_pick_str(raw.get("user_id"), raw.get("userId"), _pick_env("TRAE_USER_ID")),
    )


def load_deepseek() -> DeepSeekConfig:
    raw = _as_dict(load_raw().get("deepseek"))
    ref = raw.get("reference_balance", raw.get("referenceBalance"))
    ref_val: float | None = None
    if ref is not None and str(ref).strip() != "":
        try:
            ref_val = float(ref)
        except (TypeError, ValueError):
            ref_val = None
    return DeepSeekConfig(
        api_key=_pick_str(raw.get("api_key"), raw.get("apiKey"), _pick_env("DEEPSEEK_API_KEY", "DEEPSEEK_KEY")),
        reference_balance=ref_val,
    )
