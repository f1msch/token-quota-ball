"""Localhost JSON API used by the Tauri shell.

Reuses token_quota_ball providers, config, and ui_state. Secrets are never
logged or returned in full after they have been saved.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from token_quota_ball.config import (
    PROVIDER_IDS,
    PROVIDER_META,
    load_deepseek,
    load_raw,
    load_volc_agent_plan,
    save_raw,
    temporary_config_overlay,
)
from token_quota_ball.platform import single_instance
from token_quota_ball.platform.paths import CONFIG_PATH
from token_quota_ball.providers import fetch_provider
from token_quota_ball.providers.workbuddy import auth_file_signature, clear_key_cache
from token_quota_ball.platform.state import (
    load_state,
    normalize_provider,
    save_state,
)

from .serialize import snapshot_dict

logger = logging.getLogger("token_quota_ball.api")

DEFAULT_HOST = "127.0.0.1"
# High, uncommon port; 0 is also accepted via TOKEN_QUOTA_BALL_API_PORT.
DEFAULT_PORT = 47891
REFRESH_SECONDS = 5 * 60
LOGIN_WATCH_SECONDS = 2

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "provider_id": "cursor",
    # One cache slot per provider: switching providers must reuse that
    # provider's last snapshot instead of showing the previous provider's data.
    "snapshots": {},
    "errors": {},
    "loading": set(),
    "token": "",
}


def _mask(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 6:
        return "•" * len(text)
    return text[:2] + "••••" + text[-4:]


def _is_masked_or_blank(value: Any, previous: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text == "":
        return True
    if "••••" in text or "****" in text or "••" in text:
        return True
    if previous and text == _mask(previous):
        return True
    return False


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    if length > 1_000_000:
        raise ValueError("请求过大")
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 必须是对象")
    return data


def _public_state() -> dict[str, Any]:
    state = load_state()
    with _LOCK:
        provider_id = normalize_provider(_STATE["provider_id"])
        snap = _STATE["snapshots"].get(provider_id)
        error = _STATE["errors"].get(provider_id)
        loading = provider_id in _STATE["loading"]
    payload = snapshot_dict(snap, error)
    if snap is None:
        # No cached snapshot for this provider yet: never leave the previous
        # provider's numbers on screen. Label the ball with the new provider
        # and say it is loading instead.
        meta = PROVIDER_META[provider_id]
        payload.update(
            {
                "provider_id": provider_id,
                "title": meta["title"],
                "display_text": "加载中…" if loading else payload["display_text"],
                "status": "loading" if loading else payload["status"],
                "error": None if loading else payload["error"],
            }
        )
    return {
        "provider_id": provider_id,
        "providers": [{"id": pid, "title": PROVIDER_META[pid]["title"]} for pid in PROVIDER_IDS],
        "snapshot": payload,
        "loading": loading,
        "window": {
            "x": state.get("x"),
            "y": state.get("y"),
            "docked": bool(state.get("docked")),
            "dock_edge": state.get("dock_edge"),
            "detail_x": state.get("detail_x"),
            "detail_y": state.get("detail_y"),
        },
        "config_path": str(CONFIG_PATH),
    }


def _settings_public() -> dict[str, Any]:
    raw = load_raw()
    saved_volc = raw.get("volc_agent_plan") if isinstance(raw.get("volc_agent_plan"), dict) else {}
    saved_ds = raw.get("deepseek") if isinstance(raw.get("deepseek"), dict) else {}
    volc = load_volc_agent_plan()
    ds = load_deepseek()
    return {
        "volc_agent_plan": {
            "configured": volc.configured,
            "access_key_id": _mask(str(saved_volc.get("access_key_id") or "")),
            "has_access_key_id": bool(str(saved_volc.get("access_key_id") or "").strip()),
            "secret_access_key": _mask(str(saved_volc.get("secret_access_key") or "")),
            "has_secret_access_key": bool(str(saved_volc.get("secret_access_key") or "").strip()),
            "session_token": _mask(str(saved_volc.get("session_token") or "")),
            "has_session_token": bool(str(saved_volc.get("session_token") or "").strip()),
            "account_type": volc.account_type,
            "seat_ids": list(volc.seat_ids),
        },
        "deepseek": {
            "configured": ds.configured,
            "api_key": _mask(str(saved_ds.get("api_key") or "")),
            "has_api_key": bool(str(saved_ds.get("api_key") or "").strip()),
            "reference_balance": ds.reference_balance,
        },
        "config_path": str(CONFIG_PATH),
    }


def _build_settings_update(body: dict[str, Any]) -> dict[str, Any]:
    """Build a settings patch from the request body without writing disk."""
    # Read disk (or overlay) for mask-preserving merges.
    raw = load_raw()
    saved_volc = raw.get("volc_agent_plan") if isinstance(raw.get("volc_agent_plan"), dict) else {}
    saved_ds = raw.get("deepseek") if isinstance(raw.get("deepseek"), dict) else {}
    update: dict[str, Any] = {}

    if isinstance(body.get("volc_agent_plan"), dict):
        incoming = body["volc_agent_plan"]
        prev_ak = str(saved_volc.get("access_key_id") or "")
        prev_sk = str(saved_volc.get("secret_access_key") or "")
        prev_st = str(saved_volc.get("session_token") or "")
        account_type = str(incoming.get("account_type") or saved_volc.get("account_type") or "personal").lower()
        if account_type not in {"personal", "enterprise"}:
            account_type = "personal"
        seats_raw = incoming.get("seat_ids", saved_volc.get("seat_ids") or [])
        if isinstance(seats_raw, str):
            seats = [part.strip() for part in seats_raw.replace(";", ",").split(",") if part.strip()]
        elif isinstance(seats_raw, list):
            seats = [str(part).strip() for part in seats_raw if str(part).strip()]
        else:
            seats = []
        update["volc_agent_plan"] = {
            "access_key_id": prev_ak if _is_masked_or_blank(incoming.get("access_key_id"), prev_ak) else str(incoming.get("access_key_id") or "").strip(),
            "secret_access_key": prev_sk if _is_masked_or_blank(incoming.get("secret_access_key"), prev_sk) else str(incoming.get("secret_access_key") or "").strip(),
            "session_token": prev_st if _is_masked_or_blank(incoming.get("session_token"), prev_st) else str(incoming.get("session_token") or "").strip(),
            "account_type": account_type,
            "seat_ids": seats,
        }

    if isinstance(body.get("deepseek"), dict):
        incoming = body["deepseek"]
        prev_key = str(saved_ds.get("api_key") or "")
        ref = incoming.get("reference_balance", saved_ds.get("reference_balance"))
        if ref is None or ref == "":
            ref_val: float | str | None = ""
        else:
            try:
                ref_val = float(ref)
            except (TypeError, ValueError) as exc:
                raise ValueError("DeepSeek 参考额度必须是数字") from exc
        update["deepseek"] = {
            "api_key": prev_key if _is_masked_or_blank(incoming.get("api_key"), prev_key) else str(incoming.get("api_key") or "").strip(),
            "reference_balance": ref_val,
        }

    return update


def _merge_settings(body: dict[str, Any]) -> None:
    update = _build_settings_update(body)
    if update:
        save_raw(update)


def _refresh_provider(provider_id: str) -> None:
    """Fetch one provider off the API lock and store it in its cache slot."""
    pid = normalize_provider(provider_id)
    with _LOCK:
        _STATE["loading"].add(pid)
    view = None
    error = None
    try:
        view = fetch_provider(pid)
        error = None if view.ok else view.error
    except Exception as exc:  # noqa: BLE001
        logger.exception("查询额度失败")
        view = None
        error = str(exc) or "查询失败"
    finally:
        with _LOCK:
            _STATE["snapshots"][pid] = view
            _STATE["errors"][pid] = error
            _STATE["loading"].discard(pid)


def refresh_now(provider_id: str | None = None) -> dict[str, Any]:
    """Fetch quota synchronously (used by the explicit refresh endpoint)."""
    with _LOCK:
        pid = normalize_provider(provider_id or _STATE["provider_id"])
        _STATE["provider_id"] = pid
    _refresh_provider(pid)
    save_state({"provider_id": pid})
    return _public_state()


def switch_provider(provider_id: str) -> dict[str, Any]:
    """Switch the active provider without waiting for the network.

    The selection and its cached snapshot (or an explicit loading state) are
    returned immediately; the slow fetch keeps running on a background thread
    and the next polls pick up the fresh values.
    """
    pid = normalize_provider(provider_id)
    with _LOCK:
        _STATE["provider_id"] = pid
        _STATE["loading"].add(pid)
    save_state({"provider_id": pid})
    payload = _public_state()
    threading.Thread(target=_refresh_provider, args=(pid,), daemon=True).start()
    return payload


def _load_initial_provider() -> str:
    return normalize_provider(load_state().get("provider_id"))


class QuotaApiHandler(BaseHTTPRequestHandler):
    server_version = "TokenQuotaBallAPI/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        path = urlparse(self.path).path
        extra = ""
        if args:
            extra = " " + " ".join(str(a) for a in args[:2])
        logger.info("%s %s %s%s", self.address_string(), self.command, path, extra)

    def _cors(self) -> None:
        origin = self.headers.get("Origin") or ""
        allowed = {
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "https://tauri.localhost",
            "http://tauri.localhost",
            "tauri://localhost",
        }
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Quota-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")

    def _authorized(self) -> bool:
        expected = _STATE.get("token") or ""
        if not expected:
            return False
        got = (self.headers.get("X-Quota-Token") or "").strip()
        if not got:
            auth = (self.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        return secrets.compare_digest(got, expected)

    def _write(self, code: int, payload: dict[str, Any] | list[Any] | None = None, *, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(payload if payload is not None else {}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        self._write(code, {"ok": False, "error": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/health", "/api/health"}:
            self._write(200, {"ok": True, "status": "ready"})
            return
        if not self._authorized():
            self._error(401, "unauthorized")
            return
        if path == "/api/state":
            self._write(200, _public_state())
            return
        if path == "/api/config":
            self._write(200, _settings_public())
            return
        self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._error(401, "unauthorized")
            return
        path = urlparse(self.path).path
        try:
            body = _json_body(self)
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(400, str(exc))
            return
        try:
            if path == "/api/refresh":
                pid = body.get("provider_id")
                self._write(200, refresh_now(str(pid) if pid else None))
                return
            if path == "/api/provider":
                pid = body.get("provider_id") or body.get("id")
                if not pid:
                    self._error(400, "缺少 provider_id")
                    return
                self._write(200, switch_provider(str(pid)))
                return
            if path == "/api/config/test":
                # Overlay only: failed tests must not rewrite providers.json.
                update = _build_settings_update(body)
                pid = normalize_provider(str(body.get("provider_id") or "volc_agent_plan"))
                if pid not in ("volc_agent_plan", "deepseek"):
                    self._error(400, "只能测试火山方舟或 DeepSeek")
                    return
                with temporary_config_overlay(update):
                    view = fetch_provider(pid)
                payload = snapshot_dict(view)
                payload["ok"] = bool(view.ok)
                self._write(200, payload)
                return
        except ValueError as exc:
            self._error(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("API POST 失败")
            self._error(500, str(exc) or "服务器错误")
            return
        self._error(404, "not found")

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authorized():
            self._error(401, "unauthorized")
            return
        path = urlparse(self.path).path
        try:
            body = _json_body(self)
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(400, str(exc))
            return
        try:
            if path == "/api/config":
                _merge_settings(body)
                self._write(200, _settings_public())
                return
            if path == "/api/state":
                update = {}
                for key in ("x", "y", "docked", "dock_edge", "detail_x", "detail_y", "provider_id"):
                    if key in body:
                        update[key] = body[key]
                if "provider_id" in update:
                    update["provider_id"] = normalize_provider(update["provider_id"])
                    _STATE["provider_id"] = update["provider_id"]
                if update:
                    save_state(update)
                self._write(200, _public_state())
                return
        except ValueError as exc:
            self._error(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("API PUT 失败")
            self._error(500, str(exc) or "服务器错误")
            return
        self._error(404, "not found")


def _refresh_loop(stop: threading.Event) -> None:
    # Initial fetch is triggered in serve(); this loop keeps data warm.
    while not stop.wait(REFRESH_SECONDS):
        try:
            refresh_now()
        except Exception:  # noqa: BLE001
            logger.exception("后台刷新失败")


def _workbuddy_login_watch(stop: threading.Event) -> None:
    """桌面端登录或刷新令牌后会重写登录文件，检测到变化就立即重新鉴权。"""
    signature = auth_file_signature()
    while not stop.wait(LOGIN_WATCH_SECONDS):
        try:
            current = auth_file_signature()
        except Exception:  # noqa: BLE001
            logger.exception("检查 WorkBuddy 登录文件失败")
            continue
        if current == signature:
            continue
        signature = current
        # 登录文件可能还在写入，稍等再读，避免读到半截 JSON。
        if stop.wait(1.0):
            return
        signature = auth_file_signature()
        clear_key_cache()
        with _LOCK:
            active = _STATE["provider_id"] == "workbuddy"
        if not active:
            continue
        logger.info("检测到 WorkBuddy 登录信息更新，自动重新鉴权")
        try:
            refresh_now("workbuddy")
        except Exception:  # noqa: BLE001
            logger.exception("WorkBuddy 登录后自动刷新失败")


def serve(host: str | None = None, port: int | None = None) -> int:
    """Start the localhost API. Prints a single READY line for the Tauri shell."""
    if not single_instance.acquire():
        logger.info("已有实例在运行，退出")
        sys.stderr.write("Token Quota Ball 已在运行。\n")
        return 2

    token = (os.environ.get("TOKEN_QUOTA_BALL_API_TOKEN") or "").strip() or secrets.token_urlsafe(24)
    _STATE["token"] = token
    _STATE["provider_id"] = _load_initial_provider()

    host = host or os.environ.get("TOKEN_QUOTA_BALL_API_HOST") or DEFAULT_HOST
    if port is None:
        env_port = (os.environ.get("TOKEN_QUOTA_BALL_API_PORT") or "").strip()
        port = int(env_port) if env_port.isdigit() else DEFAULT_PORT

    httpd = ThreadingHTTPServer((host, port), QuotaApiHandler)
    actual_host, actual_port = httpd.server_address[:2]

    stop = threading.Event()
    threading.Thread(target=_refresh_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=_workbuddy_login_watch, args=(stop,), daemon=True).start()
    threading.Thread(target=lambda: refresh_now(_STATE["provider_id"]), daemon=True).start()

    # Machine-readable handshake for the Rust shell. Never includes secrets
    # other than the one-time localhost token written only to stdout.
    sys.stdout.write(f"READY {actual_host}:{actual_port} {token}\n")
    sys.stdout.flush()
    logger.info("API 已在 http://%s:%s 就绪", actual_host, actual_port)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
        single_instance.release()
        logger.info("API 已停止")
    return 0