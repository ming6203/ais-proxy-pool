"""Tests for the named proxy pool, account assignment and legacy migration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from aistudio_api.api.app import app
from aistudio_api.infrastructure.account.account_store import AccountStore
from aistudio_api.infrastructure.account.proxy_store import (
    ProxyStore,
    migrate_legacy_proxy_state,
    resolve_egress,
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture
def proxy_store(tmp_path) -> ProxyStore:
    return ProxyStore(tmp_path / "proxies.json")


@pytest.fixture
def account_store() -> AccountStore:
    return AccountStore(Path(os.environ["AISTUDIO_ACCOUNTS_DIR"]))


# ─── store ───


def test_create_named_proxy_persists(proxy_store: ProxyStore):
    profile = proxy_store.create("香港-01", "socks5://user:pass@1.2.3.4:1080", "住宅")
    assert profile.id.startswith("px_")
    assert profile.name == "香港-01"
    assert profile.url == "socks5://user:pass@1.2.3.4:1080"

    raw = json.loads(proxy_store.path.read_text(encoding="utf-8"))
    assert raw["proxies"][profile.id]["name"] == "香港-01"

    reloaded = ProxyStore(proxy_store.path)
    assert [p.name for p in reloaded.list_profiles()] == ["香港-01"]


def test_create_rejects_duplicate_name_and_url(proxy_store: ProxyStore):
    proxy_store.create("HK", "http://127.0.0.1:7890")
    with pytest.raises(ValueError, match="已存在"):
        proxy_store.create("hk", "http://127.0.0.1:7891")
    with pytest.raises(ValueError, match="已存在"):
        proxy_store.create("HK-2", "http://127.0.0.1:7890")


def test_create_rejects_invalid_or_direct_values(proxy_store: ProxyStore):
    with pytest.raises(ValueError):
        proxy_store.create("bad", "ftp://127.0.0.1:21")
    with pytest.raises(ValueError):
        proxy_store.create("direct", "direct")
    with pytest.raises(ValueError):
        proxy_store.create("", "http://127.0.0.1:7890")


def test_update_and_delete_profile(proxy_store: ProxyStore):
    profile = proxy_store.create("A", "http://127.0.0.1:7890")
    updated = proxy_store.update(profile.id, name="A-renamed", notes="note")
    assert updated is not None
    assert updated.name == "A-renamed"
    assert updated.notes == "note"

    with pytest.raises(ValueError):
        proxy_store.update(profile.id, url="socks4://127.0.0.1:1080")

    assert proxy_store.delete(profile.id) is True
    assert proxy_store.get(profile.id) is None
    assert proxy_store.delete(profile.id) is False


def test_record_probe_stores_last_result(proxy_store: ProxyStore):
    profile = proxy_store.create("probe", "http://127.0.0.1:7890")
    recorded = proxy_store.record_probe(
        profile.id, ok=True, status=204, latency_ms=88.5, checked_at=1700000000.0
    )
    assert recorded is not None
    assert recorded.last_ok is True
    assert recorded.last_status == 204
    assert recorded.last_latency_ms == 88.5


def test_resolve_egress_uses_only_pool_reference(proxy_store: ProxyStore):
    profile = proxy_store.create("HK", "socks5://1.2.3.4:1080")
    assert resolve_egress(profile.id, store=proxy_store) == "socks5://1.2.3.4:1080"
    assert resolve_egress(None, store=proxy_store) is None
    # Deleted or unknown profiles resolve to a direct connection, never a fallback.
    assert resolve_egress("px_missing", store=proxy_store) is None


# ─── account assignment ───


def test_account_proxy_profile_assignment(account_store: AccountStore, proxy_store):
    profile = proxy_store.create("HK", "socks5://1.2.3.4:1080")
    account = account_store.save_account(
        name="Pool A", email="pool-a@example.com", storage_state={"cookies": []}
    )

    updated = account_store.update_account_proxy_profile(account.id, profile.id)
    assert updated is not None and updated.proxy_id == profile.id
    assert updated.to_dict()["proxy_id"] == profile.id

    meta = json.loads(
        (account_store._accounts_dir / account.id / "meta.json").read_text()
    )
    assert meta["proxy_id"] == profile.id
    assert meta["proxy"] == ""

    cleared = account_store.update_account_proxy_profile(account.id, "")
    assert cleared is not None and cleared.proxy_id == ""
    assert cleared.to_dict()["proxy"] == ""


def test_batch_update_proxy_profile(account_store: AccountStore, proxy_store):
    profile = proxy_store.create("Batch", "socks5://5.5.5.5:1080")
    first = account_store.save_account(
        name="B1", email="batch-1@example.com", storage_state={"cookies": []}
    )
    second = account_store.save_account(
        name="B2", email="batch-2@example.com", storage_state={"cookies": []}
    )
    updated = account_store.batch_update_proxy_profile(
        [first.id, second.id], profile.id
    )
    assert {a.id for a in updated} == {first.id, second.id}
    assert account_store.get_account(second.id).proxy_id == profile.id


def test_clear_proxy_references_on_delete(account_store: AccountStore, proxy_store):
    profile = proxy_store.create("HK", "socks5://1.2.3.4:1080")
    first = account_store.save_account(
        name="A", email="clear-a@example.com", storage_state={"cookies": []}
    )
    second = account_store.save_account(
        name="B", email="clear-b@example.com", storage_state={"cookies": []}
    )
    account_store.update_account_proxy_profile(first.id, profile.id)
    account_store.update_account_proxy_profile(second.id, profile.id)

    affected = account_store.clear_proxy_references(profile.id)
    assert set(affected) == {first.id, second.id}
    assert account_store.get_account(first.id).proxy_id == ""


def test_reimport_keeps_proxy_id(account_store: AccountStore, proxy_store):
    profile = proxy_store.create("Keep", "socks5://1.2.3.4:1080")
    account = account_store.save_account(
        name="Keep",
        email="keep-pool@example.com",
        storage_state={"cookies": []},
        proxy_id=profile.id,
    )
    again = account_store.save_account(
        name="Keep", email="keep-pool@example.com", storage_state={"cookies": []}
    )
    assert again.id == account.id
    assert again.proxy_id == profile.id


# ─── legacy migration ───


def test_migrate_legacy_account_proxy_url(tmp_path, account_store: AccountStore):
    # Legacy layout: URL stored directly on the account, config.yaml network section.
    account = account_store.save_account(
        name="Legacy",
        email="legacy-proxy@example.com",
        storage_state={"cookies": []},
    )
    registry_path = account_store._accounts_dir / "registry.json"
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    raw["accounts"][account.id]["proxy"] = "socks5://9.9.9.9:1080"
    registry_path.write_text(json.dumps(raw), encoding="utf-8")
    account_store._registry = None

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "logging:\n  level: INFO\nnetwork:\n  proxy: http://8.8.8.8:7890\n",
        encoding="utf-8",
    )

    result = migrate_legacy_proxy_state(account_store, config_path=config_file)
    assert result["accounts"] >= 1
    assert result["global"] == 1

    migrated_account = account_store.get_account(account.id)
    assert migrated_account is not None
    assert migrated_account.proxy == ""
    assert migrated_account.proxy_id
    profile = (
        __import__(
            "aistudio_api.infrastructure.account.proxy_store",
            fromlist=["get_proxy_store"],
        )
        .get_proxy_store()
        .get(migrated_account.proxy_id)
    )
    assert profile is not None and profile.url == "socks5://9.9.9.9:1080"

    rewritten = config_file.read_text(encoding="utf-8")
    assert "network" not in rewritten


def test_migrate_is_idempotent(tmp_path, account_store: AccountStore):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("logging:\n  level: INFO\n", encoding="utf-8")
    first = migrate_legacy_proxy_state(account_store, config_path=config_file)
    second = migrate_legacy_proxy_state(account_store, config_path=config_file)
    assert first["global"] == 0
    assert second["global"] == 0


# ─── HTTP API ───


@pytest.mark.asyncio
async def test_proxy_pool_api_crud():
    created = await _create_via_api("香港-01", "socks5://user:pass@127.0.0.1:9")
    assert created["name"] == "香港-01"
    assert created["url_masked"] == "socks5://user:***@127.0.0.1:9"
    profile_id = created["id"]

    async with _client() as client:
        listed = await client.get("/api/proxies")
        assert listed.status_code == 200
        assert any(p["id"] == profile_id for p in listed.json())

        duplicate = await client.post(
            "/api/proxies", json={"name": "香港-01", "url": "http://1.1.1.1:7890"}
        )
        assert duplicate.status_code == 409

        invalid = await client.post(
            "/api/proxies", json={"name": "bad", "url": "ftp://x:1"}
        )
        assert invalid.status_code == 400

        updated = await client.put(
            f"/api/proxies/{profile_id}",
            json={"name": "香港-02", "notes": "住宅"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "香港-02"

        missing = await client.put("/api/proxies/px_missing", json={"name": "x"})
        assert missing.status_code == 404

        probed = await client.post(f"/api/proxies/{profile_id}/test")
        assert probed.status_code == 200
        assert probed.json()["last_ok"] is False  # closed local port

        deleted = await client.delete(f"/api/proxies/{profile_id}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True


@pytest.mark.asyncio
async def test_proxy_pool_test_endpoint_uses_probe(monkeypatch):
    from aistudio_api.infrastructure.utils import proxy_url as proxy_url_module

    async def fake_probe(proxy_url, **_kwargs):
        return {"ok": True, "status": 204, "latency_ms": 33.0, "error": ""}

    monkeypatch.setattr(proxy_url_module, "probe_proxy", fake_probe)
    async with _client() as client:
        resp = await client.post(
            "/api/proxies/test", json={"url": "socks5://1.2.3.4:1080"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["status"] == 204

        bad = await client.post("/api/proxies/test", json={"url": "ftp://x:1"})
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_delete_proxy_clears_account_reference(account_store: AccountStore):
    created = await _create_via_api("待删", "socks5://127.0.0.12:9")
    account = account_store.save_account(
        name="Ref",
        email="ref-del@example.com",
        storage_state={"cookies": []},
        proxy_id=created["id"],
    )
    async with _client() as client:
        resp = await client.delete(f"/api/proxies/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["cleared_accounts"] >= 1
    assert account_store.get_account(account.id).proxy_id == ""


@pytest.mark.asyncio
async def test_account_assigns_named_proxy_via_api(account_store: AccountStore):
    from aistudio_api.api.dependencies import get_account_service
    from aistudio_api.application.account_service import AccountService

    created = await _create_via_api("API-选择", "socks5://127.0.0.11:9")
    service = AccountService(account_store)
    account = account_store.save_account(
        name="Assign",
        email="assign-api@example.com",
        storage_state={"cookies": []},
    )
    app.dependency_overrides[get_account_service] = lambda: service
    try:
        async with _client() as client:
            resp = await client.put(
                f"/api/accounts/{account.id}/proxy",
                json={"proxy_id": created["id"]},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["proxy_id"] == created["id"]
            assert body["proxy_name"] == "API-选择"
            assert "proxy" not in body

            bad = await client.put(
                f"/api/accounts/{account.id}/proxy",
                json={"proxy_id": "px_missing"},
            )
            assert bad.status_code == 400

            cleared = await client.put(
                f"/api/accounts/{account.id}/proxy", json={"proxy_id": ""}
            )
            assert cleared.status_code == 200
            assert cleared.json()["proxy_id"] == ""
    finally:
        app.dependency_overrides.pop(get_account_service, None)


@pytest.mark.asyncio
async def test_import_binds_named_proxy(account_store: AccountStore):
    from aistudio_api.api.dependencies import get_account_service
    from aistudio_api.application.account_service import AccountService

    created = await _create_via_api("导入绑定", "socks5://127.0.0.10:9")
    cookies = json.dumps(
        [
            {"name": "SID", "value": "sid-value"},
            {"name": "SAPISID", "value": "sapisid-value"},
            {"name": "HSID", "value": "hsid-value"},
            {"name": "SSID", "value": "ssid-value"},
        ]
    )
    app.dependency_overrides[get_account_service] = lambda: AccountService(
        account_store
    )
    try:
        async with _client() as client:
            resp = await client.post(
                "/api/accounts/import-cookies",
                json={
                    "cookies": cookies,
                    "name": "导入账号",
                    "proxy_id": created["id"],
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["proxy_id"] == created["id"]
    finally:
        app.dependency_overrides.pop(get_account_service, None)

    listed = account_store.list_accounts()
    imported = next(a for a in listed if a.name == "导入账号")
    assert imported.proxy_id == created["id"]


@pytest.mark.asyncio
async def test_legacy_proxy_payload_is_rejected(account_store: AccountStore):
    from aistudio_api.api.dependencies import get_account_service
    from aistudio_api.application.account_service import AccountService

    service = AccountService(account_store)
    account = account_store.save_account(
        name="Legacy",
        email="legacy-payload@example.com",
        storage_state={"cookies": []},
    )
    app.dependency_overrides[get_account_service] = lambda: service
    try:
        async with _client() as client:
            resp = await client.put(
                f"/api/accounts/{account.id}/proxy",
                json={"proxy": "http://1.2.3.4:7890"},
            )
            assert resp.status_code in (400, 422)
            assert account_store.get_account(account.id).proxy_id == ""
    finally:
        app.dependency_overrides.pop(get_account_service, None)


async def _create_via_api(name: str, url: str) -> dict[str, object]:
    async with _client() as client:
        resp = await client.post("/api/proxies", json={"name": name, "url": url})
        assert resp.status_code == 200, resp.text
        return resp.json()
