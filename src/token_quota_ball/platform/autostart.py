"""Windows 开机自启：写入用户 Startup 目录快捷方式。"""

from __future__ import annotations

import os
from pathlib import Path

from .paths import PROJECT_ROOT


APP_NAME = "TokenQuotaBall"
SHORTCUT_NAME = "TokenQuotaBall.lnk"


def project_root() -> Path:
    return PROJECT_ROOT


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("找不到 APPDATA，无法配置开机启动。")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def launch_target() -> Path:
    """Prefer the Tauri release build; otherwise the official launcher."""
    root = project_root()
    release = root / "src" / "tauri" / "target" / "release" / "token-quota-ball.exe"
    if release.exists():
        return release
    tauri_bat = root / "scripts" / "run-tauri.bat"
    if not tauri_bat.exists():
        raise RuntimeError(f"找不到启动脚本：{tauri_bat}")
    return tauri_bat


def create_shortcut() -> Path:
    """创建开机启动快捷方式，返回快捷方式路径。"""
    target = launch_target()
    workdir = project_root()
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)

    # 用 PowerShell 创建 .lnk，避免额外依赖
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{link.as_posix()}')
$sc.TargetPath = '{target.as_posix()}'
$sc.WorkingDirectory = '{workdir.as_posix()}'
$sc.WindowStyle = 7
$sc.Description = 'Token Quota Ball 多模型额度悬浮球'
$sc.Save()
"""
    import subprocess

    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
    )
    if not link.exists():
        raise RuntimeError("快捷方式创建失败。")
    return link


def remove_shortcut() -> bool:
    link = shortcut_path()
    if link.exists():
        link.unlink()
        return True
    return False


def is_enabled() -> bool:
    return shortcut_path().exists()


def status_text() -> str:
    link = shortcut_path()
    if link.exists():
        return f"已开启开机自启\n{link}"
    return "未开启开机自启"
