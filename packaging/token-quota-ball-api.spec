# -*- mode: python ; coding: utf-8 -*-
"""将 Python 额度 API 冻结为单个 Windows exe（sidecar）。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ENTRY = ROOT / "packaging" / "api_entry.py"
OUT_NAME = "token-quota-ball-api"

datas, binaries, hiddenimports = collect_all("cryptography")

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "token_quota_ball",
        "token_quota_ball.api",
        "token_quota_ball.api.server",
        "token_quota_ball.providers",
        "token_quota_ball.providers.cursor",
        "token_quota_ball.providers.workbuddy",
        "token_quota_ball.providers.trae",
        "token_quota_ball.providers.volc_agent_plan",
        "token_quota_ball.providers.deepseek",
        "cryptography.hazmat.primitives.ciphers",
        "cryptography.hazmat.backends",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=OUT_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 保留控制台子系统，便于 READY 握手走 stdout 管道。
    # Tauri 父进程会用 CREATE_NO_WINDOW 启动，因此不会弹出控制台窗口。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
