"""Project-level paths. Config and logs live under the data home directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent


def _repo_root() -> Path:
    # PyInstaller extract dir is not the project; skip frozen lookups.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    for folder in Path(__file__).resolve().parents:
        if (folder / "pyproject.toml").is_file() and (folder / "src" / "token_quota_ball").is_dir():
            return folder
        if (folder / "config").is_dir() and (folder / "scripts").is_dir() and (folder / "src" / "token_quota_ball").is_dir():
            return folder
    # src/token_quota_ball -> src -> repo root
    return PACKAGE_DIR.parent.parent


def _looks_like_source_tree(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / "src" / "token_quota_ball").is_dir()


def _appdata_home() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "TokenQuotaBall"
    return Path.home() / "TokenQuotaBall"


def _default_home(project_root: Path) -> Path:
    """Dev: repo root. Packaged / frozen: %APPDATA%\\TokenQuotaBall."""
    if os.environ.get("TOKEN_QUOTA_BALL_HOME"):
        return Path(os.environ["TOKEN_QUOTA_BALL_HOME"]).expanduser()
    packaged = (os.environ.get("TOKEN_QUOTA_BALL_PACKAGED") or "").strip().lower()
    if packaged in {"1", "true", "yes"} or getattr(sys, "frozen", False):
        return _appdata_home()
    if _looks_like_source_tree(project_root):
        return project_root
    return _appdata_home()


PROJECT_ROOT = _repo_root()
HOME_DIR = _default_home(PROJECT_ROOT)
CONFIG_DIR = HOME_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "providers.json"
LOG_DIR = HOME_DIR / "logs"
STATE_PATH = LOG_DIR / "ui_state.json"
RUN_DIR = HOME_DIR / "run"
LOCK_PATH = RUN_DIR / "instance.lock"
