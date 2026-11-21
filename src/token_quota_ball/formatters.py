"""显示格式化。"""

from __future__ import annotations


def format_tokens_cn(n: int) -> str:
    """与官网中文展示接近：亿 / 万。"""
    if n <= 0:
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def format_usd_cents(cents: int) -> str:
    """对齐官网 Credits 卡：整数美元不带小数，否则两位。"""
    if cents % 100 == 0:
        return f"US${cents // 100}"
    return f"US${cents / 100:.2f}"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "未知"
    if seconds <= 0:
        return "已到期"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days} 天 {hours} 小时"
    if hours > 0:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分钟"
