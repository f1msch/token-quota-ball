"""python -m token_quota_ball.api — start the local quota API."""

from token_quota_ball.platform.logging_setup import setup_logging
from .server import serve


def main() -> int:
    setup_logging()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
