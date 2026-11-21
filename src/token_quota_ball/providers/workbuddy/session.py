"""WorkBuddy desktop login session: locate the auth file and reveal the token."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import load_workbuddy
from ...platform.timeutil import BEIJING_TZ as BJ
from .at_rest import is_encrypted_field, reveal_secret


logger = logging.getLogger(__name__)
AUTH_FILENAMES = ("workbuddy-desktop.info", "workbuddy-desktop-ai.info")


def auth_file_candidates(explicit: str = "") -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(os.path.expandvars(os.path.expanduser(explicit))))
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    home = Path.home()
    bases = []
    if local:
        bases.append(Path(local) / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    if roaming:
        bases.append(Path(roaming) / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    bases.append(home / ".workbuddy" / "auth")
    bases.append(home / "Library" / "Application Support" / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    bases.append(home / ".config" / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    bases.append(home / ".local" / "share" / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    for base in bases:
        for name in AUTH_FILENAMES:
            paths.append(base / name)
    # 去重并保持顺序
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def auth_file_signature() -> tuple[tuple[str, int, int], ...]:
    """本机登录文件的 (路径, mtime_ns, 大小)，用于检测桌面端完成登录或刷新令牌。"""
    cfg = load_workbuddy()
    signature: list[tuple[str, int, int]] = []
    for path in auth_file_candidates(cfg.auth_file):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _is_encrypted_field(value: Any) -> bool:
    return is_encrypted_field(value)


def _read_login_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe"):
        text = raw.decode("utf-16-le")
    elif raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16-be")
    else:
        text = raw.decode("utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("登录文件格式无法识别")
    return data


def _raw_access_token(data: dict[str, Any]) -> Any:
    for key in ("accessToken", "access_token", "token", "AccessToken"):
        if key in data:
            return data[key]
    auth = data.get("auth")
    if isinstance(auth, dict):
        return _raw_access_token(auth)
    return None


def _walk_uid(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    account = obj.get("account") if isinstance(obj.get("account"), dict) else obj
    if isinstance(account, dict):
        for key in ("uid", "userId", "user_id", "UserId", "uin", "id"):
            value = account.get(key)
            if isinstance(value, (str, int)) and str(value).strip() and not _is_encrypted_field(value):
                text = str(value).strip()
                if key == "id" and len(text) < 4:
                    continue
                return text
    for key in ("uid", "userId", "user_id", "UserId"):
        value = obj.get(key)
        if isinstance(value, (str, int)) and str(value).strip() and not _is_encrypted_field(value):
            return str(value).strip()
    return ""


def _uid_from_token(token: str) -> str:
    """登录文件里缺少 uid 时，从 JWT 载荷的 sub 兜底读取，避免手填 user id。"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part))
    except (IndexError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("sub", "userId", "user_id", "uid"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def _ms_to_dt(value: Any) -> datetime | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        if isinstance(value, str) and value.strip():
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(value.strip()[:19], fmt)
                    return dt.replace(tzinfo=BJ)
                except ValueError:
                    continue
        return None
    if number <= 0:
        return None
    if number > 1e12:
        number /= 1000.0
    return datetime.fromtimestamp(number, BJ)


def _load_auth_file(path: Path, *, app_path: str = "") -> tuple[str, str, str, str]:
    """返回 (token, uid, kind, error)。kind: plaintext / decrypted / encrypted / missing / invalid。"""
    try:
        if path.is_symlink():
            return "", "", "invalid", f"拒绝读取符号链接登录文件：{path}"
        if path.stat().st_size > 2_000_000:
            return "", "", "invalid", "登录文件过大，已跳过"
        data = _read_login_json(path)
    except FileNotFoundError:
        return "", "", "invalid", "登录文件不存在"
    except OSError as exc:
        return "", "", "invalid", f"无法读取登录文件：{exc}"
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return "", "", "invalid", "登录文件不是有效 JSON"
    uid = _walk_uid(data)
    token, kind, error = reveal_secret(
        _raw_access_token(data),
        app_path=app_path,
        hint=path.name,
        field_name="accessToken",
    )
    if token:
        return token, uid or _uid_from_token(token), kind, ""
    if error:
        return "", uid, "encrypted", error
    return "", uid, "missing", ""


def resolve_session() -> tuple[str, str, str, str | None]:
    """返回 (token, uid, source, error)。error 为加密解密失败或文件损坏等明确问题。"""
    cfg = load_workbuddy()
    if cfg.access_token:
        return cfg.access_token, cfg.user_id, "config", None
    last_err = ""
    found_file = False
    encrypted_err = ""
    for path in auth_file_candidates(cfg.auth_file):
        if not path.is_file():
            continue
        found_file = True
        token, uid, kind, err = _load_auth_file(path, app_path=cfg.app_path)
        if token:
            logger.info("已从本地 WorkBuddy 登录文件读取会话（kind=%s，不记录令牌内容）", kind)
            return token, uid or cfg.user_id, f"file:{kind}", None
        if kind == "encrypted" and err:
            encrypted_err = err
        elif err:
            last_err = err
    if encrypted_err:
        return "", "", "", encrypted_err or "未登录桌面端，无法解密本地会话。"
    if found_file and last_err:
        return "", "", "", last_err
    return "", "", "", None
