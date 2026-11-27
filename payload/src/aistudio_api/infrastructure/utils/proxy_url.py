"""Proxy URL parsing, validation, masking, and connectivity probing.

The proxy setting accepts HTTP(S) and SOCKS5 upstream proxies. An empty value
means "auto": keep the previous discovery order (environment variables, Windows
system proxy, then common local proxy ports). The literal ``direct`` marker
means "never use a proxy", which lets the operator override both the global
default and per-account inheritance.
"""

from __future__ import annotations

import time
from typing import TypedDict
from urllib.parse import urlsplit, urlunsplit

PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")
DIRECT = "direct"
_DIRECT_TOKENS = frozenset(
    {"direct", "none", "off", "no", "false", "disabled", "直连", "关闭", "不使用"}
)
_MAX_URL_LENGTH = 2048


class ProxyProbeResult(TypedDict):
    ok: bool
    status: int
    latency_ms: float
    error: str


def normalize_proxy_url(raw: object) -> str | None:
    """Validate and canonicalize a proxy setting.

    Returns ``None`` for an empty value (auto discovery), the ``DIRECT`` marker
    for an explicit bypass, or a normalized ``scheme://userinfo@host:port`` URL.
    Raises ``ValueError`` with a user-facing Chinese message on invalid input.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) > _MAX_URL_LENGTH:
        raise ValueError("代理地址过长")
    if text.lower() in _DIRECT_TOKENS:
        return DIRECT
    if "://" not in text:
        text = f"http://{text}"

    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in PROXY_SCHEMES:
        raise ValueError(
            f"不支持的代理协议 {scheme or '(空)'}，仅支持 http / https / socks5 / socks5h"
        )
    if not parts.hostname:
        raise ValueError("代理地址缺少主机名，例如 http://127.0.0.1:7890")
    if any(ch.isspace() for ch in parts.netloc):
        raise ValueError("代理地址不能包含空格")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("代理地址只能包含协议、可选账号密码、主机与端口")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("代理端口必须是 1-65535 之间的数字") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("代理端口必须是 1-65535 之间的数字")

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
        if ":" not in userinfo and not userinfo:
            raise ValueError("代理账号密码格式应为 user:pass@host:port")
        netloc = f"{userinfo}@{hostport.lower()}"
    else:
        netloc = netloc.lower()
    return urlunsplit((scheme, netloc, "", "", ""))


def is_direct(value: str | None) -> bool:
    """Whether the value explicitly disables proxying."""
    return value == DIRECT


def mask_proxy_url(url: str | None) -> str:
    """Hide credentials while keeping host/port readable for logs and API output."""
    if not url:
        return ""
    if url == DIRECT:
        return DIRECT
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid>"
    if "@" not in parts.netloc:
        return url
    userinfo, _, hostport = parts.netloc.rpartition("@")
    user = userinfo.split(":", 1)[0]
    masked = f"{user}:***@{hostport}" if user else f"***@{hostport}"
    return urlunsplit((parts.scheme, masked, "", "", ""))


def resolve_effective_proxy(
    hint: str | None, *, fallback: str | None = None
) -> str | None:
    """Resolve a per-account override against the global default.

    ``None`` inherits the fallback, ``DIRECT`` forces a direct connection, and a
    URL overrides it. The returned URL is never the ``DIRECT`` marker so callers
    can pass it straight to httpx/the signer.
    """
    if hint is None:
        return fallback
    if hint == DIRECT:
        return None
    return hint or fallback


async def probe_proxy(
    proxy_url: str | None,
    *,
    timeout: float = 8.0,
    target: str = "https://www.gstatic.com/generate_204",
) -> ProxyProbeResult:
    """Send one lightweight request through the proxy to verify connectivity."""
    import httpx

    effective = resolve_effective_proxy(proxy_url, fallback=None)
    started = time.perf_counter()
    try:
        transport = httpx.AsyncHTTPTransport(proxy=effective, http2=False)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                timeout, connect=timeout, read=timeout, write=timeout, pool=timeout
            ),
            follow_redirects=False,
        ) as client:
            response = await client.get(target)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        ok = response.status_code < 500
        return {
            "ok": ok,
            "status": response.status_code,
            "latency_ms": latency_ms,
            "error": "" if ok else f"HTTP {response.status_code}",
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        detail = str(exc) or type(exc).__name__
        return {"ok": False, "status": 0, "latency_ms": latency_ms, "error": detail}


__all__ = [
    "DIRECT",
    "PROXY_SCHEMES",
    "ProxyProbeResult",
    "is_direct",
    "mask_proxy_url",
    "normalize_proxy_url",
    "probe_proxy",
    "resolve_effective_proxy",
]
