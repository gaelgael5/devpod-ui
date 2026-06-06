from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..auth.rbac import UserInfo, require_admin
from ..config.models import GlobalConfig, HostConfig
from ..config.store import load_global, save_global

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


@router.get("/config")
async def get_admin_config(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    cfg = load_global()
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_admin_config(
    updates: dict[str, object], user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    cfg = load_global()
    merged: dict[str, object] = cfg.model_dump(mode="json")
    merged.update(updates)
    try:
        new_cfg = GlobalConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_global(new_cfg)
    _log.info("global_config_updated", by=user.login)
    return new_cfg.model_dump(mode="json")


@router.get("/hosts")
async def list_hosts(user: UserInfo = Depends(require_admin)) -> list[dict[str, object]]:
    cfg = load_global()
    return [h.model_dump(mode="json") for h in cfg.hosts]


@router.post("/hosts", status_code=201)
async def add_host(host: HostConfig, user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    cfg = load_global()
    if any(h.name == host.name for h in cfg.hosts):
        raise HTTPException(status_code=409, detail=f"Host {host.name!r} already exists")
    cfg.hosts.append(host)
    save_global(cfg)
    _log.info("host_added", name=host.name, by=user.login)
    return host.model_dump(mode="json")
