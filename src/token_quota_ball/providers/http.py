"""JSON HTTP helper shared by quota providers."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 20,
    allow_hosts: tuple[str, ...] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    """发送 JSON 请求，返回 (status, parsed_json_or_None, raw_text)。拒绝跳转到未允许的主机。"""
    req = urllib.request.Request(url, data=body, method=method.upper())
    req.add_header("Accept", "application/json")
    if body is not None and not (headers and any(k.lower() == "content-type" for k in headers)):
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, N802
            host = urllib.request.urlparse(newurl).hostname or ""
            if allow_hosts and host not in allow_hosts:
                raise urllib.error.HTTPError(newurl, code, f"拒绝跳转到 {host}", headers, fp)
            return urllib.request.HTTPRedirectHandler.redirect_request(
                self, req, fp, code, msg, headers, newurl
            )

    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        status = int(exc.code)
    text = raw.decode("utf-8", errors="replace") if raw else ""
    parsed: dict[str, Any] | list[Any] | None = None
    if text.strip():
        try:
            loaded = json.loads(text)
            if isinstance(loaded, (dict, list)):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = None
    return status, parsed, text
