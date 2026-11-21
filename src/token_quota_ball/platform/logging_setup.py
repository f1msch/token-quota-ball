"""按北京日期切换的独立日志：logs/token_quota_ball_YYYYMMDD.log"""

from __future__ import annotations

import faulthandler
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .paths import LOG_DIR
from .timeutil import BEIJING_TZ as BJ
TOOL_NAME = "token_quota_ball"


class BeijingDailyFileHandler(logging.Handler):
    terminator = "\n"

    def __init__(self, tool_name: str, log_dir: Path) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.log_dir = log_dir
        self._day = ""
        self._stream: TextIO | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = datetime.now(BJ).strftime("%Y%m%d")
            if day != self._day or self._stream is None:
                if self._stream:
                    self._stream.close()
                self.log_dir.mkdir(parents=True, exist_ok=True)
                self._stream = open(
                    self.log_dir / f"{self.tool_name}_{day}.log",
                    "a",
                    encoding="utf-8",
                )
                self._day = day
            assert self._stream is not None
            self._stream.write(self.format(record) + self.terminator)
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None
        super().close()


def _bj_converter(timestamp: float) -> tuple:
    return datetime.fromtimestamp(timestamp, BJ).timetuple()


def setup_logging(log_dir: Path | None = None) -> None:
    root = logging.getLogger()
    if getattr(root, "_logging_configured", False):
        return
    directory = log_dir or LOG_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt.converter = _bj_converter  # type: ignore[method-assign]
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    file_handler = BeijingDailyFileHandler(TOOL_NAME, directory)
    file_handler.setFormatter(fmt)
    root.addHandler(stream)
    root.addHandler(file_handler)
    setattr(root, "_logging_configured", True)

    fault_path = directory / "faulthandler.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fault_stream = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(fault_stream, all_threads=True)
        setattr(root, "_faulthandler_stream", fault_stream)
    except Exception:
        logging.getLogger(__name__).exception("无法启用 faulthandler")

    def _excepthook(exc, val, tb) -> None:  # noqa: ANN001
        logging.getLogger(__name__).error("未捕获异常", exc_info=(exc, val, tb))
        sys.__excepthook__(exc, val, tb)

    sys.excepthook = _excepthook


def now_beijing() -> datetime:
    return datetime.now(BJ)
