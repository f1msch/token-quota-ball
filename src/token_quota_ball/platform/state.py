"""Persisted provider selection and window position (logs/ui_state.json)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import PROVIDER_IDS
from .paths import STATE_PATH

logger = logging.getLogger(__name__)


def state_path() -> Path:
    path = STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_state(update: dict) -> None:
    state = load_state()
    state.update(update)
    try:
        state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("保存窗口位置失败: %s", exc)


def normalize_provider(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in PROVIDER_IDS:
        return value.strip().lower()
    return "cursor"
