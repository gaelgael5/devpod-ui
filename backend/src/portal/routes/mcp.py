from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp as db
from ..db.engine import get_conn
from ..mcp import models, service

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["mcp"])

_ID = Path(..., pattern=r"^[a-z0-9]{1,64}$")


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _map_error(exc: Exception) -> None:
    if isinstance(exc, service.NamespaceTaken):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, service.VaultLocked):
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    if isinstance(exc, service.NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, service.InvalidReference):
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ─── Backends ─────────────────────────────────────────────────────────────────


@router.get("/mcp/backends")
async def list_backends_route(
    user: UserInfo = Depends(require_user), conn: AsyncConnection = Depends(get_conn)
) -> list[dict[str, Any]]:
    return await db.list_backends(conn, user.login)


@router.post("/mcp/backends", status_code=201)
async def create_backend_route(
    body: models.BackendCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        bid = await service.create_backend(conn, user.login, body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"id": bid}


@router.patch("/mcp/backends/{backend_id}")
async def update_backend_route(
    body: models.BackendUpdate,
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    ok = await db.update_backend(
        conn, user.login, backend_id,
        name=body.name, url=body.url, transport=body.transport, enabled=body.enabled,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="backend introuvable")
    return {"id": backend_id}


@router.delete("/mcp/backends/{backend_id}", status_code=204)
async def delete_backend_route(
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_backend(conn, user.login, backend_id):
        raise HTTPException(status_code=404, detail="backend introuvable")


# ─── Clés de service ──────────────────────────────────────────────────────────


@router.get("/mcp/backends/{backend_id}/keys")
async def list_keys_route(
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    if await db.get_backend(conn, user.login, backend_id) is None:
        raise HTTPException(status_code=404, detail="backend introuvable")
    return await db.list_backend_keys(conn, backend_id)


@router.post("/mcp/backends/{backend_id}/keys", status_code=201)
async def create_key_route(
    body: models.KeyCreate,
    request: Request,
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        kid = await service.create_backend_key(conn, user.login, backend_id, _sid(request), body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"id": kid}


@router.delete("/mcp/backends/{backend_id}/keys/{key_id}", status_code=204)
async def delete_key_route(
    backend_id: str = _ID,
    key_id: str = Path(..., pattern=r"^[a-z0-9]{1,64}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if await db.get_backend(conn, user.login, backend_id) is None:
        raise HTTPException(status_code=404, detail="backend introuvable")
    if not await db.delete_backend_key(conn, backend_id, key_id):
        raise HTTPException(status_code=404, detail="clé introuvable")


# ─── Apikeys clients ──────────────────────────────────────────────────────────


@router.get("/mcp/apikeys")
async def list_apikeys_route(
    user: UserInfo = Depends(require_user), conn: AsyncConnection = Depends(get_conn)
) -> list[dict[str, Any]]:
    return await db.list_apikeys(conn, user.login)


@router.post("/mcp/apikeys", status_code=201)
async def create_apikey_route(
    body: models.ApikeyCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    aid, clear = await service.create_apikey(conn, user.login, body)
    return {"id": aid, "token": clear}


@router.post("/mcp/apikeys/{apikey_id}/revoke")
async def revoke_apikey_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    if not await db.revoke_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    return {"id": apikey_id}


@router.delete("/mcp/apikeys/{apikey_id}", status_code=204)
async def delete_apikey_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")


# ─── Grants ───────────────────────────────────────────────────────────────────


@router.get("/mcp/apikeys/{apikey_id}/grants")
async def list_grants_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    rows = await db.list_apikeys(conn, user.login)
    if not any(r["id"] == apikey_id for r in rows):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    return await db.list_grants(conn, apikey_id)


@router.put("/mcp/apikeys/{apikey_id}/grants")
async def set_grant_route(
    body: models.GrantSet,
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await service.set_grant(conn, user.login, apikey_id, body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"apikey_id": apikey_id, "backend_id": body.backend_id}


@router.delete("/mcp/apikeys/{apikey_id}/grants/{backend_id}", status_code=204)
async def delete_grant_route(
    apikey_id: str = _ID,
    backend_id: str = Path(..., pattern=r"^[a-z0-9]{1,64}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    rows = await db.list_apikeys(conn, user.login)
    if not any(r["id"] == apikey_id for r in rows):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    if not await db.delete_grant(conn, apikey_id, backend_id):
        raise HTTPException(status_code=404, detail="grant introuvable")
