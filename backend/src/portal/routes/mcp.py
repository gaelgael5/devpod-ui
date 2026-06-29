from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp as db
from ..db.engine import get_conn
from ..db.mcp_audit import list_for_owner as audit_list
from ..db.mcp_catalog import list_primitives as list_catalog_primitives
from ..mcp import models, service
from ..mcp.monitor import get_health

router = APIRouter(tags=["mcp"])

# Annotated type aliases — chaque paramètre de route reçoit une copie du FieldInfo
# (FastAPI extrait les métadonnées d'Annotated sans muter l'objet Path sous-jacent).
# NE PAS utiliser Path(...) comme valeur par défaut partagée entre plusieurs handlers :
# FastAPI/Pydantic v2 associerait l'alias du premier paramètre à tous les suivants.
_UuidId = Annotated[str, Path(pattern=r"^[a-z0-9]{1,64}$")]
_BackendId = Annotated[str, Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


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
    # Enrichi du statut de santé en mémoire (monitor, Plan 6) pour le polling UI.
    backends = await db.list_backends(conn, user.login)
    return [{**b, "health": get_health(b["id"]).status} for b in backends]


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
    backend_id: _BackendId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    ok = await db.update_backend(
        conn, user.login, backend_id,
        name=body.name, url=body.url, transport=body.transport, enabled=body.enabled,
        app_url=body.app_url,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="backend introuvable")
    return {"id": backend_id}


@router.delete("/mcp/backends/{backend_id}", status_code=204)
async def delete_backend_route(
    backend_id: _BackendId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_backend(conn, user.login, backend_id):
        raise HTTPException(status_code=404, detail="backend introuvable")


# ─── Clés de service ──────────────────────────────────────────────────────────


@router.get("/mcp/backends/{backend_id}/keys")
async def list_keys_route(
    backend_id: _BackendId,
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
    backend_id: _BackendId,
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
    backend_id: _BackendId,
    key_id: _UuidId,
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
    apikey_id: _UuidId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    if not await db.revoke_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    return {"id": apikey_id}


@router.patch("/mcp/apikeys/{apikey_id}/profile")
async def set_apikey_profile_route(
    body: models.ApikeySetProfile,
    apikey_id: _UuidId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str | None]:
    try:
        await service.set_apikey_profile(conn, user.login, apikey_id, body.profile_id)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"id": apikey_id, "profile_id": body.profile_id}


@router.get("/mcp/backends/{backend_id}/catalog")
async def list_catalog_route(
    backend_id: _BackendId,
    kind: str = "tool",
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    if await db.get_backend(conn, user.login, backend_id) is None:
        raise HTTPException(status_code=404, detail="backend introuvable")
    rows = await list_catalog_primitives(conn, backend_id, kind)
    return [
        {"name": r["original_name"], "description": (r["definition"] or {}).get("description", "")}
        for r in rows
    ]


@router.delete("/mcp/apikeys/{apikey_id}", status_code=204)
async def delete_apikey_route(
    apikey_id: _UuidId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")


# ─── Audit log ────────────────────────────────────────────────────────────────


@router.get("/mcp/audit-log")
async def list_audit_log_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
    limit: int = Query(100, ge=1, le=1000),
    status: str | None = Query(None, pattern=r"^(ok|error|denied|timeout)$"),
    tool: str | None = Query(None, max_length=256),
    since: datetime | None = Query(None),
) -> list[dict[str, Any]]:
    """Journal d'audit des appels MCP (100 derniers par défaut).

    Filtres optionnels :
    - **status** : ok | error | denied | timeout
    - **tool** : nom namespacé exact (ex: devpod__workspace_list)
    - **since** : ISO-8601, retourne uniquement les entrées après cette date
    - **limit** : 1–1000
    """
    return await audit_list(
        conn,
        user.login,
        limit=limit,
        status=status,
        tool=tool,
        since=since,
    )

