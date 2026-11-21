"""Small parsing helpers shared by provider implementations."""

from __future__ import annotations

from typing import Any


def dig(data: Any, *names: str) -> Any:
    """Look up the first non-null key, case-insensitively."""
    if not isinstance(data, dict):
        return None
    lower = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
        if name.lower() in lower and lower[name.lower()] is not None:
            return lower[name.lower()]
    return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
