"""从本机 Cursor 登录态读取 token。"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sqlite3
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

AUTH_KEYS = {
    "access_token": "cursorAuth/accessToken",
    "refresh_token": "cursorAuth/refreshToken",
    "email": "cursorAuth/cachedEmail",
    "membership": "cursorAuth/stripeMembershipType",
    "subscription_status": "cursorAuth/stripeSubscriptionStatus",
}
_STORAGE_PREFIX = "cursor-safe-storage:v1:"
_os_crypt_key_cache: bytes | None = None


@dataclass(frozen=True)
class CursorAuth:
    access_token: str
    refresh_token: str | None
    email: str | None
    membership: str | None
    subscription_status: str | None


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


class _GcmInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("dwInfoVersion", wintypes.ULONG),
        ("pbNonce", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbNonce", wintypes.ULONG),
        ("pbAuthData", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbAuthData", wintypes.ULONG),
        ("pbTag", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbTag", wintypes.ULONG),
        ("pbMacContext", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbMacContext", wintypes.ULONG),
        ("cbAAD", wintypes.ULONG),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", wintypes.ULONG),
    ]


def state_db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        win = Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        if win.exists():
            return win

    home = Path.home()
    for path in (
        home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
        home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
    ):
        if path.exists():
            return path
    raise FileNotFoundError("未找到 Cursor 本地数据库，请确认已安装并登录 Cursor。")


def load_auth() -> CursorAuth:
    db_path = state_db_path()
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=5)
    try:
        values: dict[str, str | None] = {}
        for field, key in AUTH_KEYS.items():
            row = con.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            values[field] = row[0] if row and row[0] else None
    finally:
        con.close()

    token = _reveal_secret(values["access_token"], db_path)
    if not token:
        raise RuntimeError("未找到 accessToken，请先在 Cursor 中登录账号。")

    return CursorAuth(
        access_token=token,
        refresh_token=_reveal_secret(values["refresh_token"], db_path),
        email=values["email"],
        membership=values["membership"],
        subscription_status=values["subscription_status"],
    )


def _reveal_secret(stored: str | None, db_path: Path) -> str | None:
    if not stored or not stored.startswith(_STORAGE_PREFIX):
        return stored
    if sys.platform != "win32":
        raise RuntimeError("Cursor 登录态已加密，当前系统还不能解密。")
    blob = base64.b64decode(stored[len(_STORAGE_PREFIX) :])
    if len(blob) < 3 + 12 + 16 or not blob.startswith(b"v10"):
        raise RuntimeError("无法解密 Cursor 登录态。")
    plain = _aes_gcm_decrypt(_os_crypt_key(db_path), blob[3:15], blob[15:-16], blob[-16:])
    return plain.decode("utf-8")


def _os_crypt_key(db_path: Path) -> bytes:
    global _os_crypt_key_cache
    if _os_crypt_key_cache is not None:
        return _os_crypt_key_cache
    local_state = db_path.parents[2] / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        encrypted = base64.b64decode(data["os_crypt"]["encrypted_key"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("无法解密 Cursor 登录态。") from exc
    if not encrypted.startswith(b"DPAPI"):
        raise RuntimeError("无法解密 Cursor 登录态。")
    key = _dpapi_unprotect(encrypted[5:])
    _os_crypt_key_cache = key
    return key


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("无法解密 Cursor 登录态。")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    bcrypt = ctypes.windll.bcrypt
    alg = ctypes.c_void_p()
    handle = ctypes.c_void_p()
    status = bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg), "AES", None, 0)
    if status:
        raise RuntimeError("无法解密 Cursor 登录态。")
    try:
        chain = ctypes.create_unicode_buffer("ChainingModeGCM")
        status = bcrypt.BCryptSetProperty(alg, "ChainingMode", chain, ctypes.sizeof(chain), 0)
        if status:
            raise RuntimeError("无法解密 Cursor 登录态。")
        key_buf = ctypes.create_string_buffer(key, len(key))
        status = bcrypt.BCryptGenerateSymmetricKey(
            alg, ctypes.byref(handle), None, 0, key_buf, len(key), 0
        )
        if status:
            raise RuntimeError("无法解密 Cursor 登录态。")
        nonce_buf = (ctypes.c_ubyte * len(nonce)).from_buffer_copy(nonce)
        tag_buf = (ctypes.c_ubyte * len(tag)).from_buffer_copy(tag)
        info = _GcmInfo()
        info.cbSize = ctypes.sizeof(_GcmInfo)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nonce_buf, ctypes.POINTER(ctypes.c_ubyte))
        info.cbNonce = len(nonce)
        info.pbTag = ctypes.cast(tag_buf, ctypes.POINTER(ctypes.c_ubyte))
        info.cbTag = len(tag)
        in_buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        out = ctypes.create_string_buffer(len(ciphertext))
        done = wintypes.ULONG()
        status = bcrypt.BCryptDecrypt(
            handle,
            in_buf,
            len(ciphertext),
            ctypes.byref(info),
            None,
            0,
            out,
            len(ciphertext),
            ctypes.byref(done),
            0,
        )
        if status:
            raise RuntimeError("无法解密 Cursor 登录态。")
        return out.raw[: done.value]
    finally:
        if handle:
            bcrypt.BCryptDestroyKey(handle)
        bcrypt.BCryptCloseAlgorithmProvider(alg, 0)
