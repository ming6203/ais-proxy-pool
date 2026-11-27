"""Named egress proxy pool persisted in ``data/proxies.json``.

Operators keep a list of named proxies (one per account) instead of retyping
URLs. Credentials live in the data directory rather than ``config.yaml`` so they
are not committed with the repository.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

import yaml

from aistudio_api.config import resolve_data_dir
from aistudio_api.infrastructure.utils.common import atomic_write_json
from aistudio_api.infrastructure.utils.proxy_url import (
    DIRECT,
    normalize_proxy_url,
)

_MAX_NAME_LENGTH = 64
_MAX_NOTES_LENGTH = 500


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_name(name: object) -> str:
    text = str(name or "").strip()
    if not text:
        raise ValueError("代理名称不能为空")
    if len(text) > _MAX_NAME_LENGTH:
        raise ValueError(f"代理名称不能超过 {_MAX_NAME_LENGTH} 个字符")
    return text


def _clean_url(url: object) -> str:
    normalized = normalize_proxy_url(url)
    if normalized is None:
        raise ValueError("代理地址不能为空")
    if normalized == DIRECT:
        raise ValueError("代理池只保存真实代理地址，强制直连请在账号上单独选择")
    return normalized


@dataclass
class ProxyProfile:
    """A named upstream proxy available for account assignment."""

    id: str
    name: str
    url: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_checked_at: float | None = None
    last_ok: bool | None = None
    last_status: int | None = None
    last_latency_ms: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProxyProfile:
        def _opt_float(key: str) -> float | None:
            raw = data.get(key)
            if raw is None:
                return None
            try:
                return float(str(raw))
            except (TypeError, ValueError):
                return None

        def _opt_int(key: str) -> int | None:
            raw = data.get(key)
            if raw is None:
                return None
            try:
                return int(str(raw))
            except (TypeError, ValueError):
                return None

        raw_ok = data.get("last_ok")
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            url=str(data.get("url") or ""),
            notes=str(data.get("notes") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            last_checked_at=_opt_float("last_checked_at"),
            last_ok=bool(raw_ok) if raw_ok is not None else None,
            last_status=_opt_int("last_status"),
            last_latency_ms=_opt_float("last_latency_ms"),
        )


class ProxyStore:
    """Thread-safe, atomically persisted proxy pool."""

    _instances: ClassVar[dict[Path, ProxyStore]] = {}
    _singleton_lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls, store_path: Path | None = None) -> ProxyStore:
        resolved = (store_path or _default_store_path()).resolve()
        with cls._singleton_lock:
            if resolved not in cls._instances:
                cls._instances[resolved] = super().__new__(cls)
            return cls._instances[resolved]

    def __init__(self, store_path: Path | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._path = (store_path or _default_store_path()).resolve()
        self._lock = threading.RLock()
        self._cache: dict[str, ProxyProfile] | None = None
        self._initialized = True

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, ProxyProfile]:
        with self._lock:
            if self._cache is not None:
                return self._cache
            profiles: dict[str, ProxyProfile] = {}
            if self._path.is_file():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    items = raw.get("proxies") if isinstance(raw, dict) else None
                    if isinstance(items, dict):
                        for pid, item in items.items():
                            if isinstance(item, dict):
                                profile = ProxyProfile.from_dict(item)
                                profiles[str(pid)] = profile
                except Exception:
                    profiles = {}
            self._cache = profiles
            return profiles

    def _save(self, profiles: dict[str, ProxyProfile]) -> None:
        with self._lock:
            self._cache = profiles
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self._path,
                {"proxies": {pid: p.to_dict() for pid, p in profiles.items()}},
                compact=True,
            )

    def list_profiles(self) -> list[ProxyProfile]:
        with self._lock:
            return list(self._load().values())

    def get(self, profile_id: str) -> ProxyProfile | None:
        with self._lock:
            return self._load().get(str(profile_id or ""))

    def find_by_url(self, url: str) -> ProxyProfile | None:
        target = normalize_proxy_url(url)
        with self._lock:
            return next(
                (p for p in self._load().values() if p.url == target),
                None,
            )

    def create(self, name: str, url: str, notes: str = "") -> ProxyProfile:
        clean_name = _clean_name(name)
        clean_url = _clean_url(url)
        with self._lock:
            profiles = self._load()
            if any(
                p.name.casefold() == clean_name.casefold() for p in profiles.values()
            ):
                raise ValueError(f"代理名称已存在: {clean_name}")
            if any(p.url == clean_url for p in profiles.values()):
                raise ValueError("该代理地址已存在于代理池中")
            now = _now_iso()
            profile = ProxyProfile(
                id=f"px_{secrets.token_hex(4)}",
                name=clean_name,
                url=clean_url,
                notes=str(notes or "")[:_MAX_NOTES_LENGTH],
                created_at=now,
                updated_at=now,
            )
            profiles[profile.id] = profile
            self._save(profiles)
            return profile

    def update(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        notes: str | None = None,
    ) -> ProxyProfile | None:
        with self._lock:
            profiles = self._load()
            profile = profiles.get(str(profile_id or ""))
            if profile is None:
                return None
            if name is not None:
                clean_name = _clean_name(name)
                if any(
                    pid != profile.id and p.name.casefold() == clean_name.casefold()
                    for pid, p in profiles.items()
                ):
                    raise ValueError(f"代理名称已存在: {clean_name}")
                profile.name = clean_name
            if url is not None:
                clean_url = _clean_url(url)
                if any(
                    pid != profile.id and p.url == clean_url
                    for pid, p in profiles.items()
                ):
                    raise ValueError("该代理地址已存在于代理池中")
                profile.url = clean_url
            if notes is not None:
                profile.notes = str(notes)[:_MAX_NOTES_LENGTH]
            profile.updated_at = _now_iso()
            self._save(profiles)
            return profile

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            profiles = self._load()
            if str(profile_id or "") not in profiles:
                return False
            del profiles[str(profile_id)]
            self._save(profiles)
            return True

    def record_probe(
        self,
        profile_id: str,
        *,
        ok: bool,
        status: int,
        latency_ms: float,
        checked_at: float,
    ) -> ProxyProfile | None:
        with self._lock:
            profiles = self._load()
            profile = profiles.get(str(profile_id or ""))
            if profile is None:
                return None
            profile.last_checked_at = checked_at
            profile.last_ok = ok
            profile.last_status = status
            profile.last_latency_ms = latency_ms
            self._save(profiles)
            return profile


def _default_store_path() -> Path:
    return resolve_data_dir() / "proxies.json"


def get_proxy_store(store_path: Path | None = None) -> ProxyStore:
    return ProxyStore(store_path)


def resolve_egress(
    proxy_id: str | None, *, store: ProxyStore | None = None
) -> str | None:
    """Resolve an account's named proxy to a concrete URL (``None`` = direct)."""
    if not proxy_id:
        return None
    profile = (store or get_proxy_store()).get(proxy_id)
    return profile.url if profile is not None else None


def resolve_account_egress(auth_file: str | Path | None) -> str | None:
    """Resolve egress for the account owning ``auth_file`` from meta.json."""
    from aistudio_api.infrastructure.account.cookie_parser import (
        get_proxy_id_from_meta,
    )

    return resolve_egress(get_proxy_id_from_meta(auth_file))


def _unique_profile_name(store: ProxyStore, base: str) -> str:
    names = {p.name.casefold() for p in store.list_profiles()}
    if base.casefold() not in names:
        return base
    for index in range(2, 100):
        candidate = f"{base} #{index}"
        if candidate.casefold() not in names:
            return candidate
    return f"{base} #{secrets.token_hex(2)}"


def _profile_for_url(store: ProxyStore, url: str, base_name: str) -> ProxyProfile:
    existing = store.find_by_url(url)
    if existing is not None:
        return existing
    return store.create(_unique_profile_name(store, base_name), url)


def migrate_legacy_proxy_state(
    account_store: object,
    config_path: Path | None = None,
) -> dict[str, int]:
    """Move pre-pool proxy settings into named pool profiles.

    Legacy layouts kept an operator-wide proxy in ``config.yaml`` (``network.proxy``)
    and a free-form URL on each account (``AccountMeta.proxy``). Both are migrated
    once into the named pool and then cleared, so the pool is the single source.
    """
    store = get_proxy_store()
    migrated_accounts = 0
    migrated_global = 0

    legacy_global: str | None = None
    path = config_path or _config_path()
    if path is not None and path.is_file():
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            network = parsed.get("network")
            if isinstance(network, dict):
                raw = str(network.get("proxy") or "").strip()
                if raw:
                    try:
                        normalized = normalize_proxy_url(raw)
                    except ValueError:
                        normalized = None
                    if normalized and normalized != DIRECT:
                        legacy_global = normalized
                if "proxy" in network:
                    network.pop("proxy", None)
                    if network:
                        parsed["network"] = network
                    else:
                        parsed.pop("network", None)
                    _write_config(path, parsed)

    if legacy_global:
        _profile_for_url(store, legacy_global, "迁移-全局代理")
        migrated_global = 1

    accounts = getattr(account_store, "list_accounts", list)()
    for account in accounts:
        legacy_url = str(getattr(account, "proxy", "") or "").strip()
        if not legacy_url:
            continue
        try:
            normalized = normalize_proxy_url(legacy_url)
        except ValueError:
            normalized = None
        proxy_id = getattr(account, "proxy_id", "") or ""
        if normalized and normalized != DIRECT and not proxy_id:
            host = _host_label(normalized)
            profile = _profile_for_url(store, normalized, f"迁移-{host}")
            updater = getattr(account_store, "assign_legacy_proxy_profile", None)
            if callable(updater):
                updater(account.id, profile.id)
                migrated_accounts += 1
                continue
        clearer = getattr(account_store, "clear_legacy_proxy_url", None)
        if callable(clearer):
            clearer(account.id)

    return {"global": migrated_global, "accounts": migrated_accounts}


def _host_label(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "旧代理"
    host = parts.hostname or "旧代理"
    port = parts.port
    return f"{host}:{port}" if port else host


def _config_path() -> Path | None:
    try:
        from aistudio_api.config import resolve_config_file

        return resolve_config_file()
    except Exception:
        return None


def _write_config(path: Path, parsed: dict[str, object]) -> None:
    from aistudio_api.infrastructure.utils.common import atomic_write_text

    atomic_write_text(path, yaml.dump(parsed, allow_unicode=True, sort_keys=False))


__all__ = [
    "ProxyProfile",
    "ProxyStore",
    "get_proxy_store",
    "migrate_legacy_proxy_state",
    "resolve_account_egress",
    "resolve_egress",
]
