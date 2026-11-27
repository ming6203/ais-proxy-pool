"""Tests for proxy URL handling, proxy-pool egress plumbing and signer payloads."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from aistudio_api.config import settings
from aistudio_api.infrastructure.account.account_store import AccountStore
from aistudio_api.infrastructure.account.proxy_store import (
    ProxyStore,
    get_proxy_store,
)
from aistudio_api.infrastructure.gateway.session import GatewaySession, SessionContext
from aistudio_api.infrastructure.gateway.transport import HTTPStreamTransport
from aistudio_api.infrastructure.utils.proxy_url import (
    DIRECT,
    mask_proxy_url,
    normalize_proxy_url,
    probe_proxy,
    resolve_effective_proxy,
)

# ─── URL parsing ───


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        (None, None),
        ("   ", None),
        ("127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("HTTPS://Proxy.Example.com:443", "https://proxy.example.com:443"),
        ("socks5://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("socks5h://user:pass@127.0.0.1:1080", "socks5h://user:pass@127.0.0.1:1080"),
        ("direct", DIRECT),
        (" OFF ", DIRECT),
        ("直连", DIRECT),
    ],
)
def test_normalize_proxy_url_accepts_supported_forms(raw, expected):
    assert normalize_proxy_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://127.0.0.1:21",
        "http://",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:7890/path",
        "http://127.0.0.1:7890?mode=global",
        "http://bad host:7890",
    ],
)
def test_normalize_proxy_url_rejects_invalid_forms(raw):
    with pytest.raises(ValueError):
        normalize_proxy_url(raw)


def test_mask_proxy_url_hides_credentials_only():
    assert mask_proxy_url("http://user:secret@1.2.3.4:7890") == (
        "http://user:***@1.2.3.4:7890"
    )
    assert mask_proxy_url("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"
    assert mask_proxy_url(None) == ""


def test_resolve_effective_proxy_semantics():
    assert resolve_effective_proxy(None, fallback=None) is None
    assert resolve_effective_proxy("socks5://10.0.0.1:1080") == (
        "socks5://10.0.0.1:1080"
    )
    assert resolve_effective_proxy(DIRECT) is None


@pytest.mark.asyncio
async def test_probe_proxy_reports_connect_failure_without_client_config_errors():
    result = await probe_proxy("http://127.0.0.1:9", timeout=2.0)
    assert result["ok"] is False
    assert result["status"] == 0
    assert result["error"]
    assert "Timeout must" not in result["error"]


# ─── account meta / session ───


@pytest.fixture
def store(tmp_path) -> ProxyStore:
    return ProxyStore(tmp_path / "proxies.json")


@pytest.fixture
def account_store() -> AccountStore:
    import os
    from pathlib import Path

    return AccountStore(Path(os.environ["AISTUDIO_ACCOUNTS_DIR"]))


def test_account_store_persists_proxy_reference(account_store: AccountStore, store):
    profile = store.create("HK", "socks5://1.2.3.4:1080")
    account = account_store.save_account(
        name="Ref", email="ref-store@example.com", storage_state={"cookies": []}
    )
    updated = account_store.update_account_proxy_profile(account.id, profile.id)
    assert updated is not None and updated.proxy_id == profile.id
    assert updated.to_dict()["proxy_id"] == profile.id

    meta = json.loads(
        (account_store._accounts_dir / account.id / "meta.json").read_text()
    )
    assert meta["proxy_id"] == profile.id

    cleared = account_store.update_account_proxy_profile(account.id, "")
    assert cleared is not None and cleared.proxy_id == ""


@pytest.mark.asyncio
async def test_session_context_carries_pool_proxy(tmp_path):
    store = get_proxy_store()
    profile = store.create(f"会话-{id(tmp_path)}", "socks5://127.0.0.1:1087")
    account_dir = tmp_path / f"acc_{id(tmp_path)}"
    account_dir.mkdir()
    auth_file = account_dir / "auth.json"
    auth_file.write_text(
        json.dumps({"cookies": [{"name": "SID", "value": "x"}]}), encoding="utf-8"
    )
    (account_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": account_dir.name,
                "auth_user": "0",
                "tier": "Free",
                "proxy_id": profile.id,
            }
        ),
        encoding="utf-8",
    )

    session = GatewaySession()
    try:
        ctx = await session.transition_to_account(str(auth_file))
        assert ctx.proxy_url == "socks5://127.0.0.1:1087"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_session_without_pool_proxy_is_direct():
    session = GatewaySession()
    try:
        fake_transport = MagicMock(spec=HTTPStreamTransport)
        fake_transport.send_request = AsyncMock(return_value=(200, b"[]"))
        session._transport = fake_transport
        ctx = SessionContext(auth_user="0", cookies={"SID": "x"})
        await session.send_request(body="{}", ctx=ctx)
        assert fake_transport.send_request.await_args.kwargs["proxy_url"] is None
    finally:
        await session.close()


# ─── transport ───


@pytest.mark.asyncio
async def test_transport_keeps_one_pool_per_distinct_proxy(monkeypatch):
    transport = HTTPStreamTransport()
    created: list[str | None] = []

    class FakeClient:
        def __init__(self, proxy: str | None) -> None:
            self.proxy = proxy
            self.is_closed = False

    def fake_build(proxy: str | None) -> FakeClient:
        created.append(proxy)
        return FakeClient(proxy)

    monkeypatch.setattr(transport, "_build_client", fake_build)

    shared_a = await transport._get_client("socks5://127.0.0.1:1080")
    shared_b = await transport._get_client("socks5://127.0.0.1:1080")
    other = await transport._get_client("http://127.0.0.1:7890")
    direct = await transport._get_client(DIRECT)

    assert shared_a is shared_b
    assert shared_a is not other
    assert created == [
        "socks5://127.0.0.1:1080",
        "http://127.0.0.1:7890",
        None,
    ]
    assert direct is transport._client


@pytest.mark.asyncio
async def test_transport_ignores_process_level_proxy(monkeypatch):
    """Account traffic never inherits the process-level (env/system) proxy."""
    transport = HTTPStreamTransport()
    created: list[str | None] = []

    class FakeClient:
        def __init__(self, proxy: str | None) -> None:
            self.proxy = proxy
            self.is_closed = False

    monkeypatch.setattr(settings, "proxy_url", "http://127.0.0.1:7890")
    monkeypatch.setattr(
        transport,
        "_build_client",
        lambda proxy: (created.append(proxy), FakeClient(proxy))[1],
    )

    pooled = await transport._get_client(None)
    assert isinstance(pooled, FakeClient)
    assert pooled.proxy is None
    assert created == [None]


# ─── signer ───


@pytest.mark.asyncio
async def test_signer_forwards_proxy_and_defaults_to_direct(monkeypatch):
    from aistudio_api.infrastructure.waa.daemon import LocalSignerProcess
    from aistudio_api.infrastructure.waa.signer import LocalIpcProofSigner

    captured: dict[str, object] = {}

    async def fake_request(method: str, params=None, **_kwargs):
        captured.clear()
        captured.update(params or {})
        return {"id": 1, "ok": True, "proof": "!p", "poolState": "hot"}

    fake_proc = MagicMock(spec=LocalSignerProcess)
    fake_proc.request = AsyncMock(side_effect=fake_request)
    signer = LocalIpcProofSigner(process=fake_proc)

    await signer.mint_proof(
        cookies={"SAPISID": "x"},
        auth_user="0",
        prompt="hi",
        proxy="socks5://127.0.0.1:1080",
    )
    assert captured["proxy"] == "socks5://127.0.0.1:1080"

    await signer.mint_proof(cookies={"SAPISID": "x"}, auth_user="0", prompt="hi")
    assert captured["proxy"] == DIRECT
