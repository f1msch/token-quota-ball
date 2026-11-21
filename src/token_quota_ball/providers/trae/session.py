"""Trae CN desktop login session: locate and open the local auth blob.

Trae CN（本机 Trae IDE）把登录态存在
``%APPDATA%\\Trae CN\\User\\globalStorage\\storage.json`` 的
``iCubeAuthInfo://icube.cloudide`` 键里。值本身是 base64 的自定义信封：

    b"tc" + 0x05 + 0x10 + b"\\x00\\x00" + 32 字节随机密钥 + AES-128-CBC(...)

明文是 ``SHA-512(data) + data``，``data`` 为包含 ``token`` / ``host`` /
``userId`` / ``account`` 的用户信息 JSON。密钥内嵌在信封里，KDF 为：

    n = SHA-512(key) + (OPE XOR APE)
    aesKey, iv = SHA-512(n)[:16], SHA-512(n)[16:32]

``~/.trae-cn/trae-jwt-token`` 是另一套临时 token，不能用于额度接口。
本模块只读取本机登录态，不写回、不打印 token。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ...config import load_trae

logger = logging.getLogger(__name__)

AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
DEFAULT_HOST = "https://api.trae.cn"
_MAGIC = b"tc"
_VERSION = 5
_KEY_OFFSET = 6
_KEY_LEN = 32
_DIGEST_LEN = 64

# Trae byteCrypto 混淆表（与 IDE 内 KDF 常量一致）。
_OPE = bytes(
    (
        82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
        124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
        84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
        8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
    )
)
_APE = bytes(
    (
        31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
        96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
        160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
        23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
    )
)


class TraeSessionError(RuntimeError):
    """Raised when the local auth blob exists but cannot be opened."""


class TraeNotLoggedIn(TraeSessionError):
    """Raised when Trae is installed but not signed in."""


@dataclass(frozen=True)
class TraeSession:
    token: str
    host: str = DEFAULT_HOST
    user_id: str = ""
    username: str = ""
    region: str = ""
    source: str = ""
    expires_at: str = ""


def _derive(key: bytes) -> tuple[bytes, bytes]:
    buffer = bytearray(128)
    buffer[0:64] = hashlib.sha512(key).digest()
    buffer[64:128] = bytes(left ^ right for left, right in zip(_OPE, _APE))
    buffer[0:64] = hashlib.sha512(bytes(buffer)).digest()
    return bytes(buffer[:16]), bytes(buffer[16:32])


def decrypt_auth_blob(blob: bytes) -> dict[str, Any]:
    if len(blob) < _KEY_OFFSET + _KEY_LEN + 16:
        raise TraeSessionError("Trae 登录信息过短，无法解密")
    if blob[:2] != _MAGIC:
        raise TraeSessionError("Trae 登录信息不是已知的 tc 信封")
    if blob[2] != _VERSION:
        raise TraeSessionError(f"暂不支持 Trae 登录信息版本 {blob[2]}，可能 IDE 已升级")
    key = blob[_KEY_OFFSET:_KEY_OFFSET + _KEY_LEN]
    ciphertext = blob[_KEY_OFFSET + _KEY_LEN:]
    aes_key, iv = _derive(key)
    decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    pad = plain[-1] if plain else 0
    if 1 <= pad <= 16 and len(plain) > pad:
        plain = plain[:-pad]
    if len(plain) <= _DIGEST_LEN:
        raise TraeSessionError("Trae 登录信息解密结果不完整")
    digest, body = plain[:_DIGEST_LEN], plain[_DIGEST_LEN:]
    if hashlib.sha512(body).digest() != digest:
        raise TraeSessionError("Trae 登录信息校验失败，可能 IDE 升级后改了格式")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraeSessionError("Trae 登录信息不是有效的用户 JSON") from exc
    if not isinstance(data, dict):
        raise TraeSessionError("Trae 登录信息格式无法识别")
    return data


def data_dir_candidates(explicit: str = "") -> list[Path]:
    if explicit:
        return [Path(os.path.expandvars(os.path.expanduser(explicit)))]
    paths: list[Path] = []
    roaming = os.environ.get("APPDATA")
    if roaming:
        paths.append(Path(roaming) / "Trae CN")
        paths.append(Path(roaming) / "Trae")
    home = Path.home()
    paths.append(home / "Library" / "Application Support" / "Trae CN")
    paths.append(home / ".config" / "Trae CN")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _storage_candidates(explicit: str = "") -> list[Path]:
    return [base / "User" / "globalStorage" / "storage.json" for base in data_dir_candidates(explicit)]


def _read_auth_info(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise TraeSessionError("拒绝读取符号链接登录文件")
        if path.stat().st_size > 8_000_000:
            raise TraeSessionError("Trae storage.json 过大，已跳过")
        storage = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraeSessionError(f"无法读取 Trae storage.json：{exc}") from exc
    if not isinstance(storage, dict):
        raise TraeSessionError("Trae storage.json 不是 JSON 对象")
    encoded = storage.get(AUTH_KEY)
    if not isinstance(encoded, str) or not encoded.strip():
        raise TraeNotLoggedIn("storage.json 里没有 Trae 登录信息")
    try:
        blob = base64.b64decode(encoded, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise TraeSessionError("Trae 登录信息不是有效 base64") from exc
    return decrypt_auth_blob(blob)


def _session_from_info(info: dict[str, Any], source: str) -> TraeSession | None:
    token = str(info.get("token") or "").strip()
    if not token:
        return None
    account = info.get("account") if isinstance(info.get("account"), dict) else {}
    region_info = info.get("userRegion") if isinstance(info.get("userRegion"), dict) else {}
    return TraeSession(
        token=token,
        host=str(info.get("host") or DEFAULT_HOST).strip(),
        user_id=str(info.get("userId") or "").strip(),
        username=str(account.get("username") or "").strip(),
        region=str(region_info.get("region") or "").strip(),
        source=source,
        expires_at=str(info.get("expiredAt") or "").strip(),
    )


def resolve_session() -> tuple[TraeSession | None, str]:
    """返回 (登录会话, 错误信息)。未安装/未登录时返回 (None, "")。"""
    cfg = load_trae()
    if cfg.token:
        return (
            TraeSession(
                token=cfg.token,
                host=cfg.host or DEFAULT_HOST,
                user_id=cfg.user_id,
                source="config",
            ),
            "",
        )
    last_error = ""
    for path in _storage_candidates(cfg.data_dir):
        if not path.is_file():
            continue
        try:
            info = _read_auth_info(path)
        except TraeNotLoggedIn:
            continue
        except TraeSessionError as exc:
            last_error = str(exc)
            continue
        session = _session_from_info(info, f"storage:{path.name}")
        if session is not None:
            logger.info("已从本机 Trae CN 登录态读取会话（不记录令牌内容）")
            return session, ""
    return None, last_error
