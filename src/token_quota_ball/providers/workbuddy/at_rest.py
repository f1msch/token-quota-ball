"""Decrypt WorkBuddy desktop login fields sealed as ``$wbEncrypted`` envelopes.

WorkBuddy 5.6+ / 5.7.6+ stores ``accessToken`` / ``refreshToken`` (and some
account fields) as::

    {"$wbEncrypted": 1, "envelope": "<base64 JSON>"}

The envelope is AES-256-GCM (suite=1) with
``{suite, keyId, nonce, authTag, ciphertext}``.

The field key is not stored on disk. This module asks the installed WorkBuddy
desktop app for it by running the app binary with ``ELECTRON_RUN_AS_NODE=1``
and calling ``electron_browser_workbuddy_storage.loggerGet()``. The payload
contains ``atRestSecretKey`` (a base64 string). The 32-byte key is
``SHA-256(atRestSecretKey as UTF-8 text)`` — the string is hashed, not the
decoded bytes. ``keyId`` is ``SHA-256(key).hex()[:16]``.

Field-level AAD (WBEV1 / sym-v1) is::

    b"WB-AAD\\0" + 0x01 + LP("WBEV1") + LP("sym-v1") + u32be(suite)
    + LP(keyId) + 0x02 + 0x00 + 0x00

where ``LP(s)`` is ``u32be(len(utf-8(s))) + utf-8(s)``.

This module never scans process memory, never writes the secret or a token to
disk or log lines, and never writes plaintext back into the login file.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

ENVELOPE_FLAG = "$wbEncrypted"
AAD_DOMAIN = b"WB-AAD\0"
FRAMING_CODE_FIELD = 2
FORMAT_ID_FIELD = "WBEV1"
SCHEME = "sym-v1"
DEFAULT_SUITE = 1
KEY_CACHE_TTL_SEC = 10 * 60
KEY_FETCH_TIMEOUT_SEC = 20
HELPER_SCRIPT = (
    "try{process.stdout.write(String(process._linkedBinding("
    "'electron_browser_workbuddy_storage').loggerGet()))}"
    "catch(e){process.exitCode=3;process.stderr.write(String((e&&e.message)||e))}"
)
EXE_NAMES = ("WorkBuddy.exe", "WorkBuddyAI.exe")
CREATE_NO_WINDOW = 0x08000000

_key_cache: dict[str, tuple[float, bytes, str]] = {}


class AtRestError(RuntimeError):
    """Raised when an encrypted field cannot be opened."""


def is_encrypted_field(value: Any) -> bool:
    """True if *value* is a ``$wbEncrypted`` wrapper (dict or JSON string)."""
    if isinstance(value, dict):
        return ENVELOPE_FLAG in value and isinstance(value.get("envelope"), str)
    if isinstance(value, str):
        text = value.lstrip()
        return text.startswith("{") and ENVELOPE_FLAG in text[:80]
    return False


def _as_wrapper(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AtRestError("加密字段不是有效的 JSON 信封") from exc
    if not isinstance(value, dict) or not is_encrypted_field(value):
        raise AtRestError("不是 WorkBuddy 的 $wbEncrypted 加密字段")
    return value


def parse_envelope(value: Any) -> dict[str, Any]:
    wrapper = _as_wrapper(value)
    blob = wrapper.get("envelope") or ""
    try:
        record = json.loads(base64.b64decode(blob).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AtRestError("envelope 不是 base64(JSON)") from exc
    if not isinstance(record, dict):
        raise AtRestError("envelope 解码后不是 JSON 对象")
    try:
        suite = int(record.get("suite") or DEFAULT_SUITE)
        key_id = str(record.get("keyId") or "")
        nonce = base64.b64decode(record["nonce"])
        auth_tag = base64.b64decode(record["authTag"])
        ciphertext = base64.b64decode(record["ciphertext"])
    except Exception as exc:  # noqa: BLE001
        raise AtRestError("envelope 缺少 suite/keyId/nonce/authTag/ciphertext") from exc
    if suite != DEFAULT_SUITE:
        raise AtRestError(f"暂不支持的加密套件 suite={suite}，当前只支持 suite=1（AES-256-GCM）")
    if not re.fullmatch(r"[0-9a-f]{16}", key_id or ""):
        raise AtRestError("envelope keyId 格式无效")
    if len(nonce) != 12 or len(auth_tag) != 16:
        raise AtRestError("envelope 的 nonce 或 authTag 长度不符合 AES-256-GCM")
    return {
        "suite": suite,
        "key_id": key_id,
        "nonce": nonce,
        "auth_tag": auth_tag,
        "ciphertext": ciphertext,
    }


def _u32(value: int) -> bytes:
    return int(value).to_bytes(4, "big")


def _length_prefixed(text: str) -> bytes:
    raw = text.encode("utf-8")
    return _u32(len(raw)) + raw


def build_field_aad(key_id: str, suite: int) -> bytes:
    return b"".join(
        (
            AAD_DOMAIN,
            bytes([1]),
            _length_prefixed(FORMAT_ID_FIELD),
            _length_prefixed(SCHEME),
            _u32(suite),
            _length_prefixed(key_id),
            bytes([FRAMING_CODE_FIELD, 0, 0]),
        )
    )


def derive_at_rest_key(payload_json: str) -> bytes:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise AtRestError("桌面端 loggerGet() 返回的不是 JSON 密钥载荷") from exc
    secret = payload.get("atRestSecretKey") if isinstance(payload, dict) else None
    if not isinstance(secret, str) or not secret:
        raise AtRestError("桌面端密钥载荷里没有 atRestSecretKey")
    # The desktop app hashes the base64 STRING, not the decoded bytes.
    return hashlib.sha256(secret.encode("utf-8")).digest()


def derive_key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def decrypt_envelope(key: bytes, value: Any) -> str:
    env = parse_envelope(value)
    expected = derive_key_id(key)
    if env["key_id"] != expected:
        raise AtRestError(
            f"信封 keyId={env['key_id']} 与当前桌面端密钥（{expected}）不匹配。"
            "可能安装了国内版和国际版两套客户端，请确认已登录的是正在使用的那一套。"
        )
    aad = build_field_aad(env["key_id"], env["suite"])
    try:
        plain = AESGCM(key).decrypt(env["nonce"], env["ciphertext"] + env["auth_tag"], aad)
    except Exception as exc:  # noqa: BLE001
        raise AtRestError("AES-256-GCM 解密失败，密钥或信封可能已失效") from exc
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AtRestError("解密结果不是有效文本") from exc


def _quoted_path(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    match = re.search(r'"([^"]+\.exe)"', text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    cleaned = text.strip().strip('"')
    cleaned = re.sub(r",\s*-?\d+$", "", cleaned)
    if cleaned.lower().endswith(".exe"):
        return cleaned
    return ""


def _add_exe(found: list[Path], raw: str | Path | None) -> None:
    if not raw:
        return
    path = Path(os.path.expandvars(os.path.expanduser(str(raw))))
    try:
        path = path.resolve()
    except OSError:
        return
    if path.is_file() and path not in found:
        found.append(path)


def _registry_exe_candidates() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg

    results: list[str] = []

    def read_default(key_path: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            return
        parsed = _quoted_path(str(value))
        if parsed:
            results.append(parsed)

    for name in EXE_NAMES:
        read_default(rf"Software\Classes\Applications\{name}\shell\open\command")

    uninstall_roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, root in uninstall_roots:
        try:
            with winreg.OpenKey(hive, root) as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for index in range(count):
                    try:
                        sub_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, sub_name) as sub:
                            display = ""
                            icon = ""
                            location = ""
                            try:
                                display, _ = winreg.QueryValueEx(sub, "DisplayName")
                            except OSError:
                                pass
                            try:
                                icon, _ = winreg.QueryValueEx(sub, "DisplayIcon")
                            except OSError:
                                pass
                            try:
                                location, _ = winreg.QueryValueEx(sub, "InstallLocation")
                            except OSError:
                                pass
                    except OSError:
                        continue
                    title = str(display or "")
                    if not re.match(r"WorkBuddy", title, flags=re.IGNORECASE):
                        continue
                    parsed = _quoted_path(str(icon))
                    if parsed:
                        results.append(parsed)
                    if location:
                        for exe_name in EXE_NAMES:
                            results.append(str(Path(str(location)) / exe_name))
        except OSError:
            continue
    return results


def _common_install_candidates() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA") or ""
    program = os.environ.get("ProgramFiles") or ""
    program86 = os.environ.get("ProgramFiles(x86)") or ""
    roots = [Path(p) for p in (local, Path(local) / "Programs" if local else "", program, program86) if p]
    subdirs = ("WorkBuddy", "WorkBuddy AI", "WorkBuddyAI")
    found: list[Path] = []
    for root in roots:
        for sub in subdirs:
            for name in EXE_NAMES:
                _add_exe(found, root / sub / name)
    return found


def _where_candidates() -> list[Path]:
    found: list[Path] = []
    for name in EXE_NAMES:
        try:
            proc = subprocess.run(
                ["where.exe", name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                text=True,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (proc.stdout or "").splitlines():
            _add_exe(found, line.strip())
    return found


def discover_workbuddy_executables(explicit: str = "") -> list[Path]:
    """Locate WorkBuddy / WorkBuddy AI executables without assuming a fixed folder."""
    found: list[Path] = []
    _add_exe(found, explicit)
    for env_name in (
        "WORKBUDDY_APP_EXECUTABLE",
        "WORKBUDDY_ELECTRON_BIN",
        "WORKBUDDY_AI_ELECTRON_BIN",
    ):
        _add_exe(found, os.environ.get(env_name))
    for raw in _registry_exe_candidates():
        _add_exe(found, raw)
    for path in _common_install_candidates():
        _add_exe(found, path)
    for path in _where_candidates():
        _add_exe(found, path)
    return found


def _prefer_edition(candidates: list[Path], hint: str = "") -> list[Path]:
    hint = hint.lower()
    want_ai = "ai" in hint or "workbuddy-desktop-ai" in hint

    def score(path: Path) -> int:
        name = path.name.lower()
        is_ai = "ai" in name
        if want_ai:
            return 0 if is_ai else 1
        return 0 if name == "workbuddy.exe" else 1

    return sorted(candidates, key=score)


def fetch_key_payload(executable: Path) -> str:
    if not executable.is_file():
        raise AtRestError(f"找不到 WorkBuddy 可执行文件：{executable}")
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        proc = subprocess.run(
            [str(executable), "-e", HELPER_SCRIPT],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=KEY_FETCH_TIMEOUT_SEC,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise AtRestError("从桌面端读取 at-rest 密钥超时，请确认 WorkBuddy 已正确安装") from exc
    except OSError as exc:
        raise AtRestError(f"无法启动 WorkBuddy 以读取密钥：{exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().replace("\n", " ")[:180]
        detail = err or f"退出码 {proc.returncode}"
        raise AtRestError(f"桌面端 loggerGet() 未返回密钥载荷：{detail}")
    return proc.stdout.decode("utf-8", "replace").strip()


def resolve_at_rest_key(explicit_app: str = "", target_key_id: str = "", hint: str = "") -> bytes:
    """Return the derived 32-byte field key. Cached per executable for 10 minutes."""
    now = time.monotonic()
    candidates = _prefer_edition(discover_workbuddy_executables(explicit_app), hint)
    if not candidates:
        raise AtRestError(
            "未找到 WorkBuddy 桌面端可执行文件，无法自动解密。"
            "请安装并登录本机 WorkBuddy 桌面端。"
        )

    last_error: AtRestError | None = None
    fallback_key: bytes | None = None
    for exe in candidates:
        slot = str(exe)
        cached = _key_cache.get(slot)
        if cached and now - cached[0] < KEY_CACHE_TTL_SEC:
            _fetched_at, key, key_id = cached
            if not target_key_id or key_id == target_key_id:
                return key
            fallback_key = fallback_key or key
            continue
        try:
            payload = fetch_key_payload(exe)
            key = derive_at_rest_key(payload)
            key_id = derive_key_id(key)
            _key_cache[slot] = (now, key, key_id)
            logger.info("已从本机 WorkBuddy 桌面端取得 at-rest 密钥（不记录密钥内容）")
            if not target_key_id or key_id == target_key_id:
                return key
            fallback_key = fallback_key or key
        except AtRestError as exc:
            last_error = exc
            _key_cache.pop(slot, None)
    if fallback_key is not None:
        return fallback_key
    if last_error is not None:
        raise last_error
    raise AtRestError("未能从本机 WorkBuddy 桌面端取得 at-rest 密钥")


def clear_key_cache() -> None:
    _key_cache.clear()


def open_encrypted_field(value: Any, *, app_path: str = "", hint: str = "") -> str:
    """Decrypt one ``$wbEncrypted`` field and return the plaintext string."""
    env = parse_envelope(value)
    key = resolve_at_rest_key(app_path, target_key_id=env["key_id"], hint=hint)
    try:
        return decrypt_envelope(key, value)
    except AtRestError as exc:
        if "不匹配" in str(exc) or "解密失败" in str(exc):
            clear_key_cache()
            key = resolve_at_rest_key(app_path, target_key_id=env["key_id"], hint=hint)
            return decrypt_envelope(key, value)
        raise


def reveal_secret(
    value: Any,
    *,
    app_path: str = "",
    hint: str = "",
    field_name: str = "accessToken",
) -> tuple[str, str, str | None]:
    """Return ``(plaintext, kind, error)``.

    *kind* is ``plaintext`` or ``decrypted``. On failure *plaintext* is empty and
    *error* explains why, including that the field is encrypted.
    """
    if isinstance(value, str) and value.strip() and not is_encrypted_field(value):
        return value.strip(), "plaintext", None
    if not is_encrypted_field(value):
        return "", "missing", None
    try:
        text = open_encrypted_field(value, app_path=app_path, hint=hint).strip()
    except AtRestError as exc:
        return "", "encrypted", f"{field_name} 已加密，自动解密失败：{exc}"
    if not text:
        return "", "encrypted", f"{field_name} 已加密，解密结果为空"
    return text, "decrypted", None
