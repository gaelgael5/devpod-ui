from __future__ import annotations

import asyncio
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..agents.resync import resync_owner_workspaces
from ..auth.rbac import UserInfo, require_user
from ..db import mcp as mcp_db
from ..db import mcp_profiles as db
from ..db.engine import get_conn
from ..mcp.service import new_id

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["mcp-profiles"])

# Annotated type aliases — cf. mcp.py pour la justification du choix Annotated vs constante Path.
_ProfileId = Annotated[str, Path(pattern=r"^[a-z0-9]{1,64}$")]
_BackendId = Annotated[str, Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""


class EntryUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # null = première clé enabled du backend (auto-résolution).
    backend_key_id: str | None = None
    # null = tous les tools, [] = aucun, liste = subset explicite.
    tools: list[str] | None = None


# ─── Profils ──────────────────────────────────────────────────────────────────


@router.get("/mcp/profiles")
async def list_profiles_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await db.list_profiles(conn, user.login)


@router.post("/mcp/profiles", status_code=201)
async def create_profile_route(
    body: ProfileCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    pid = new_id()
    await db.insert_profile(
        conn, id=pid, owner_login=user.login, name=body.name, description=body.description
    )
    return {"id": pid}


@router.get("/mcp/profiles/{profile_id}")
async def get_profile_route(
    profile_id: _ProfileId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    profile = await db.get_profile(conn, user.login, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profil introuvable")
    entries = await db.list_profile_entries(conn, profile_id)
    return {**profile, "entries": entries}


@router.put("/mcp/profiles/{profile_id}")
async def update_profile_route(
    body: ProfileUpdate,
    profile_id: _ProfileId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    updated = await db.update_profile(
        conn, user.login, profile_id, name=body.name, description=body.description
    )
    if not updated:
        raise HTTPException(status_code=404, detail="profil introuvable")
    return {"id": profile_id}


class ExposedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exposed: bool


# Références fortes sur les resyncs fire-and-forget (sinon GC possible mi-course).
_resync_tasks: set[asyncio.Task[Any]] = set()


def _spawn_resync(login: str, only_ws_ids: set[str] | None) -> None:
    task = asyncio.create_task(resync_owner_workspaces(login, only_ws_ids))
    _resync_tasks.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _resync_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            _log.error("agent_resync_task_failed", login=login, exc_info=t.exception())

    task.add_done_callback(_done)


@router.put("/mcp/profiles/{profile_id}/exposed")
async def set_profile_exposed_route(
    body: ExposedUpdate,
    profile_id: _ProfileId,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    """(Dé)coche « exposé aux workspaces » (spec 35 §3).

    Décochage = fail closed immédiat : flag + révocation des clefs dérivées dans
    une transaction dédiée, committée AVANT de lancer le resync. Ne PAS utiliser
    la connexion de requête + BackgroundTasks ici : l'ordre commit/tâche n'est pas
    garanti par FastAPI (constaté sur test1 : resync lisant l'état d'avant, et
    rollback silencieux du décochage). Le resync est un asyncio.create_task
    fire-and-forget dont l'échec est loggé — les clefs révoquées restent le
    fail closed même si la régénération des fichiers échoue."""
    from ..db.engine import _get_engine

    affected: list[str] = []
    unexposed: list[dict[str, Any]] = []
    async with _get_engine().begin() as conn:
        if not await db.set_profile_exposed(conn, user.login, profile_id, exposed=body.exposed):
            raise HTTPException(status_code=404, detail="profil introuvable")
        if body.exposed:
            # Exposition EXCLUSIVE (fiche 0073f02e) : un seul profil alimente les
            # workspaces. Le précédent est décoché et ses clefs révoquées dans la
            # même transaction — l'utilisateur a confirmé la coupure des agents.
            unexposed = await db.unexpose_other_profiles(conn, user.login, profile_id)
            for prev in unexposed:
                affected += await mcp_db.revoke_profile_workspace_apikeys(
                    conn, user.login, str(prev["id"])
                )
            affected = sorted(set(affected))
        else:
            affected = await mcp_db.revoke_profile_workspace_apikeys(conn, user.login, profile_id)
    # Transaction committée — le resync lit l'état à jour.
    if body.exposed:
        _spawn_resync(user.login, None)
    elif affected:
        _spawn_resync(user.login, set(affected))
    _log.info(
        "mcp_profile_exposed_set",
        login=user.login,
        profile_id=profile_id,
        exposed=body.exposed,
        revoked_workspaces=affected,
        unexposed_profiles=[str(p["id"]) for p in unexposed],
    )
    return {
        "id": profile_id,
        "exposed": body.exposed,
        "affected_workspaces": affected,
        "unexposed_profiles": [str(p["name"]) for p in unexposed],
    }


@router.delete("/mcp/profiles/{profile_id}", status_code=204)
async def delete_profile_route(
    profile_id: _ProfileId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_profile(conn, user.login, profile_id):
        raise HTTPException(status_code=404, detail="profil introuvable")


# ─── Entries ──────────────────────────────────────────────────────────────────


@router.put("/mcp/profiles/{profile_id}/entries/{backend_id}")
async def upsert_entry_route(
    body: EntryUpsert,
    profile_id: _ProfileId,
    backend_id: _BackendId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    if await db.get_profile(conn, user.login, profile_id) is None:
        raise HTTPException(status_code=404, detail="profil introuvable")
    if not await mcp_db.backend_exists(conn, backend_id):
        raise HTTPException(status_code=404, detail="backend introuvable")
    if (
        body.backend_key_id is not None
        and await mcp_db.get_backend_key(conn, backend_id, body.backend_key_id) is None
    ):
        raise HTTPException(status_code=404, detail="clé backend introuvable")
    await db.upsert_profile_entry(
        conn,
        profile_id=profile_id,
        backend_id=backend_id,
        backend_key_id=body.backend_key_id,
        tools=body.tools,
    )
    return {"profile_id": profile_id, "backend_id": backend_id}


@router.delete("/mcp/profiles/{profile_id}/entries/{backend_id}", status_code=204)
async def delete_entry_route(
    profile_id: _ProfileId,
    backend_id: _BackendId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if await db.get_profile(conn, user.login, profile_id) is None:
        raise HTTPException(status_code=404, detail="profil introuvable")
    if not await db.delete_profile_entry(conn, profile_id, backend_id):
        raise HTTPException(status_code=404, detail="entry introuvable")
