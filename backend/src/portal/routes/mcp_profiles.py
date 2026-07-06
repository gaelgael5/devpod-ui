from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
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


@router.put("/mcp/profiles/{profile_id}/exposed")
async def set_profile_exposed_route(
    body: ExposedUpdate,
    profile_id: _ProfileId,
    background: BackgroundTasks,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """(Dé)coche « exposé aux workspaces » (spec 35 §3).

    Décochage = fail closed immédiat : les clefs workspace dérivées du profil sont
    révoquées dans la même transaction ; la régénération des fichiers sur les hosts
    part en tâche de fond APRÈS commit (les tokens révoqués deviennent inertes même
    si un push échoue). Cochage : resync de tous les workspaces à agents (nouvelles
    entrées + clefs)."""
    if not await db.set_profile_exposed(conn, user.login, profile_id, exposed=body.exposed):
        raise HTTPException(status_code=404, detail="profil introuvable")
    affected: list[str] = []
    if body.exposed:
        background.add_task(resync_owner_workspaces, user.login, None)
    else:
        affected = await mcp_db.revoke_profile_workspace_apikeys(conn, user.login, profile_id)
        if affected:
            background.add_task(resync_owner_workspaces, user.login, set(affected))
    _log.info(
        "mcp_profile_exposed_set",
        login=user.login,
        profile_id=profile_id,
        exposed=body.exposed,
        revoked_workspaces=affected,
    )
    return {"id": profile_id, "exposed": body.exposed, "affected_workspaces": affected}


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
