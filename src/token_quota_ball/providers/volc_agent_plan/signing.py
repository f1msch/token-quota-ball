"""Volcengine OpenAPI V4 request signing for Ark Agent Plan."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote

HOST = "ark.cn-beijing.volcengineapi.com"
REGION = "cn-beijing"
SERVICE = "ark"
CONTENT_TYPE = "application/json"


def _hmac(key: bytes, content: str) -> bytes:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _norm_query(params: dict[str, str]) -> str:
    parts: list[str] = []
    for key in sorted(params.keys()):
        parts.append(f"{quote(key, safe='-_.~')}={quote(params[key], safe='-_.~')}")
    return "&".join(parts).replace("+", "%20")


def sign_headers(
    *,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    method: str,
    query: dict[str, str],
    body: str,
    now: datetime | None = None,
    host: str = HOST,
    region: str = REGION,
    service: str = SERVICE,
) -> dict[str, str]:
    """按火山引擎官方 OpenAPI V4 示例计算签名头。"""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    x_date = moment.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    x_content_sha256 = _sha256_hex(body)
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical = "\n".join(
        [
            method.upper(),
            "/",
            _norm_query(query),
            f"content-type:{CONTENT_TYPE}",
            f"host:{host}",
            f"x-content-sha256:{x_content_sha256}",
            f"x-date:{x_date}",
            "",
            signed_headers,
            x_content_sha256,
        ]
    )
    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(["HMAC-SHA256", x_date, scope, _sha256_hex(canonical)])
    k_date = _hmac(secret_key.encode("utf-8"), short_date)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, "request")
    signature = _hmac(k_signing, string_to_sign).hex()
    headers = {
        "Content-Type": CONTENT_TYPE,
        "Host": host,
        "X-Content-Sha256": x_content_sha256,
        "X-Date": x_date,
        "Authorization": (
            f"HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    if session_token:
        # 临时凭证：官方说明需带 X-Security-Token。为保持与示例一致，默认不把它算进 SignedHeaders。
        headers["X-Security-Token"] = session_token
    return headers
