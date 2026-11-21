from __future__ import annotations

import logging
import sys

from token_quota_ball.platform.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    from token_quota_ball.platform import autostart

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in {"install-autostart", "--install-autostart"}:
            path = autostart.create_shortcut()
            print(f"已开启开机自启：\n{path}")
            logging.getLogger(__name__).info("已开启开机自启")
            return 0
        if cmd in {"uninstall-autostart", "--uninstall-autostart"}:
            removed = autostart.remove_shortcut()
            print("已关闭开机自启。" if removed else "当前未配置开机自启。")
            return 0
        if cmd in {"autostart-status", "--autostart-status"}:
            print(autostart.status_text())
            return 0
        if cmd in {"-h", "--help", "help"}:
            _print_help()
            return 0
        print(f"未知命令：{sys.argv[1]}")
        _print_help()
        return 2

    _print_help()
    return 0


def _print_help() -> None:
    print(
        "请使用 scripts\\run-tauri.bat 启动悬浮球。\n"
        "本命令只提供开机自启等管理功能（在工具根目录 token-quota-ball/ 下，并把 PYTHONPATH 设为 src）：\n"
        "  python -m token_quota_ball install-autostart   开机自启\n"
        "  python -m token_quota_ball uninstall-autostart 取消自启\n"
        "  python -m token_quota_ball autostart-status    查看状态\n"
        "或使用 scripts\\install-autostart.bat / uninstall-autostart.bat\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
