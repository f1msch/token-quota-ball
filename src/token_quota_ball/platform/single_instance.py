"""单实例锁，避免开机重复打开多个窗口。"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

from .paths import LOCK_PATH, RUN_DIR

_LOCK_FILE: Path | None = None
_LOCK_FD: int | None = None

# Windows GetExitCodeProcess: process is still running.
_STILL_ACTIVE = 259


def acquire() -> bool:
    """拿到锁返回 True；已有实例返回 False。"""
    global _LOCK_FILE, _LOCK_FD
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE = LOCK_PATH
    flags = os.O_CREAT | os.O_RDWR
    if sys.platform == "win32":
        # Windows：独占创建失败则先看旧锁是不是残留。
        try:
            _LOCK_FD = os.open(str(_LOCK_FILE), flags | os.O_EXCL)
        except FileExistsError:
            try:
                if _lock_is_live(_LOCK_FILE):
                    return False
                _LOCK_FILE.unlink(missing_ok=True)
                _LOCK_FD = os.open(str(_LOCK_FILE), flags | os.O_EXCL)
            except OSError:
                return False
    else:
        import fcntl

        _LOCK_FD = os.open(str(_LOCK_FILE), flags)
        try:
            fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(_LOCK_FD)
            _LOCK_FD = None
            return False

    os.ftruncate(_LOCK_FD, 0)
    os.write(_LOCK_FD, str(os.getpid()).encode("utf-8"))
    atexit.register(release)
    return True


def _lock_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip().split()
    except OSError:
        return None
    if not raw or not raw[0].isdigit():
        return None
    return int(raw[0])


def _lock_is_live(path: Path) -> bool:
    """True if a healthy backend still holds the lock.

    A lock file that points at a dead PID, a reused PID, or an orphaned
    ``token_quota_ball.api`` process (parent already gone) is treated as stale
    so a later launch can start. Orphaned backends are stopped so they do not
    keep the localhost port.
    """
    pid = _lock_pid(path)
    if pid is None or not _pid_alive(pid):
        return False
    if sys.platform == "win32":
        if not _is_our_backend(pid):
            return False
        parent = _parent_pid(pid)
        if parent is None or parent <= 0 or not _pid_alive(parent):
            _terminate_pid(pid)
            return False
    return True


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        if not ok:
            return False
        return exit_code.value == _STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parent_pid(pid: int) -> int | None:
    if sys.platform != "win32" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1, ctypes.c_void_p(-1).value):
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.th32ProcessID == pid:
                return int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


def _is_our_backend(pid: int) -> bool:
    line = _windows_command_line(pid).lower()
    return "token_quota_ball" in line


def _windows_command_line(pid: int) -> str:
    if sys.platform != "win32" or pid <= 0:
        return ""
    import subprocess

    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or "").strip()


def _terminate_pid(pid: int) -> None:
    if sys.platform != "win32" or pid <= 0 or pid == os.getpid():
        return
    import ctypes

    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return
    try:
        ctypes.windll.kernel32.TerminateProcess(handle, 1)
        ctypes.windll.kernel32.WaitForSingleObject(handle, 2000)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def release() -> None:
    global _LOCK_FD, _LOCK_FILE
    if _LOCK_FD is not None:
        try:
            os.close(_LOCK_FD)
        except OSError:
            pass
        _LOCK_FD = None
    if _LOCK_FILE is not None:
        try:
            _LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        _LOCK_FILE = None
