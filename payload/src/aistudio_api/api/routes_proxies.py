"""Named egress proxy pool management routes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Path as FastApiPath
from pydantic import BaseModel

from aistudio_api.api.dependencies import get_runtime_state
from aistudio_api.infrastructure.account.account_store import AccountStore
from aistudio_api.infrastructure.account.proxy_store import (
    ProxyProfile,
    get_proxy_store,
)
from aistudio_api.infrastructure.utils.logger import get_logger
from aistudio_api.infrastructure.utils.proxy_url import mask_proxy_url

if TYPE_CHECKING:
    from aistudio_api.api.state import RuntimeState

log = get_logger("proxies")

router = APIRouter(prefix="/proxies")

_PROXY_ID_PATTERN = r"^[a-zA-Z0-9_\-\.]+$"


class ProxyProfileResponse(BaseModel):
    id: str
    name: str
    url: str
    url_masked: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_checked_at: float | None = None
    last_ok: bool | None = None
    last_status: int | None = None
    last_latency_ms: float | None = None
    account_count: int = 0


class CreateProxyRequest(BaseModel):
    name: str
    url: str
    notes: str = ""


class UpdateProxyProfileRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    notes: str | None = None


class ProxyProbeRequest(BaseModel):
    url: str


class ProxyProbeResponse(BaseModel):
    ok: bool
    status: int
    latency_ms: float
    error: str = ""
    proxy: str = ""


def _account_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for account in AccountStore().list_accounts():
        proxy_id = getattr(account, "proxy_id", "") or ""
        if proxy_id:
            counts[proxy_id] = counts.get(proxy_id, 0) + 1
    return counts


def to_response(profile: ProxyProfile, account_count: int = 0) -> ProxyProfileResponse:
    return ProxyProfileResponse(
        id=profile.id,
        name=profile.name,
        url=profile.url,
        url_masked=mask_proxy_url(profile.url),
        notes=profile.notes,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        last_checked_at=profile.last_checked_at,
        last_ok=profile.last_ok,
        last_status=profile.last_status,
        last_latency_ms=profile.last_latency_ms,
        account_count=account_count,
    )


def _raise_bad_request(exc: ValueError) -> NoReturn:
    message = str(exc)
    status = 409 if "已存在" in message else 400
    raise HTTPException(status_code=status, detail=message) from exc


@router.get("", response_model=list[ProxyProfileResponse])
@router.get("/", response_model=list[ProxyProfileResponse])
async def list_proxy_profiles() -> list[ProxyProfileResponse]:
    """列出代理池中的全部命名代理及其被账号引用数量。"""
    store = get_proxy_store()
    counts = _account_counts()
    return [
        to_response(profile, counts.get(profile.id, 0))
        for profile in store.list_profiles()
    ]


@router.post("", response_model=ProxyProfileResponse)
async def create_proxy_profile(req: CreateProxyRequest) -> ProxyProfileResponse:
    """新增命名代理（名称与地址均需唯一）。"""
    try:
        profile = get_proxy_store().create(req.name, req.url, req.notes)
    except ValueError as exc:
        _raise_bad_request(exc)
    log.info("新增代理: %s (%s)", profile.name, mask_proxy_url(profile.url))
    return to_response(profile, 0)


@router.post("/test", response_model=ProxyProbeResponse)
async def test_proxy_url(req: ProxyProbeRequest = Body(...)) -> ProxyProbeResponse:
    """在保存前测试一个代理地址的连通性。"""
    from aistudio_api.infrastructure.utils.proxy_url import (
        normalize_proxy_url,
        probe_proxy,
    )

    try:
        normalized = normalize_proxy_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"代理地址无效: {exc}") from exc
    if normalized is None:
        raise HTTPException(status_code=400, detail="代理地址不能为空")
    result = await probe_proxy(normalized, timeout=15.0)
    return ProxyProbeResponse(
        ok=bool(result["ok"]),
        status=int(result["status"]),
        latency_ms=float(result["latency_ms"]),
        error=str(result["error"]),
        proxy=mask_proxy_url(normalized),
    )


@router.put("/{proxy_id}", response_model=ProxyProfileResponse)
async def update_proxy_profile(
    proxy_id: str = FastApiPath(..., pattern=_PROXY_ID_PATTERN),
    req: UpdateProxyProfileRequest = Body(...),
) -> ProxyProfileResponse:
    """修改命名代理的名称、地址或备注。"""
    try:
        profile = get_proxy_store().update(
            proxy_id, name=req.name, url=req.url, notes=req.notes
        )
    except ValueError as exc:
        _raise_bad_request(exc)
    if profile is None:
        raise HTTPException(status_code=404, detail="代理不存在")
    counts = _account_counts()
    log.info("更新代理: %s (%s)", profile.name, mask_proxy_url(profile.url))
    return to_response(profile, counts.get(profile.id, 0))


@router.delete("/{proxy_id}")
async def delete_proxy_profile(
    proxy_id: str = FastApiPath(..., pattern=_PROXY_ID_PATTERN),
    runtime_state: RuntimeState = Depends(get_runtime_state),
) -> dict[str, object]:
    """删除命名代理，并解除所有账号对它的引用（回落到全局代理）。"""
    store = get_proxy_store()
    profile = store.get(proxy_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="代理不存在")
    affected = AccountStore().clear_proxy_references(proxy_id)
    store.delete(proxy_id)

    account_service = getattr(runtime_state, "account_service", None)
    client_obj = getattr(runtime_state, "client", None)
    gateway_session = client_obj.session if client_obj is not None else None
    if account_service is not None and gateway_session is not None:
        active = account_service.get_active_account()
        if (
            active is not None
            and active.id in affected
            and gateway_session.active_context is not None
        ):
            gateway_session.active_context.proxy_url = None
    log.info("删除代理: %s，解除账号引用 %d 个", profile.name, len(affected))
    return {"ok": True, "cleared_accounts": len(affected)}


@router.post("/{proxy_id}/test", response_model=ProxyProfileResponse)
async def test_proxy_profile(
    proxy_id: str = FastApiPath(..., pattern=_PROXY_ID_PATTERN),
) -> ProxyProfileResponse:
    """测试命名代理连通性并把结果记录到代理池。"""
    from aistudio_api.infrastructure.utils.proxy_url import probe_proxy

    store = get_proxy_store()
    profile = store.get(proxy_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="代理不存在")
    result = await probe_proxy(profile.url, timeout=15.0)
    checked_at = time.time()
    updated = store.record_probe(
        proxy_id,
        ok=bool(result["ok"]),
        status=int(result["status"]),
        latency_ms=float(result["latency_ms"]),
        checked_at=checked_at,
    )
    counts = _account_counts()
    return to_response(updated or profile, counts.get(proxy_id, 0))


__all__ = ["router", "to_response"]
