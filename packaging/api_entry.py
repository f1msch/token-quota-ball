"""PyInstaller 入口：启动本机额度 API。"""

from __future__ import annotations

import sys


def main() -> int:
    from token_quota_ball.platform.logging_setup import setup_logging
    from token_quota_ball.api.server import serve

    setup_logging()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
