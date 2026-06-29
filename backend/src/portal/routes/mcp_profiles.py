from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp as mcp_db
from ..db import mcp_profiles as db
from ..db.engine import get_conn
from ..mcp.service import new_id

router = APIRouter(tags=["mcp-profiles"])

_ID = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,80}$")


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
    profile_id: str = _ID,
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
    profile_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    updated = await db.update_profile(
        conn, user.login, profile_id, name=body.name, description=body.description
    )
    if not updated:
        raise HTTPException(status_code=404, detail="profil introuvable")
    return {"id": profile_id}


@router.delete("/mcp/profiles/{profile_id}", status_code=204)
async def delete_profile_route(
    profile_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_profile(conn, user.login, profile_id):
        raise HTTPException(status_code=404, detail="profil introuvable")


# ─── Entries ──────────────────────────────────────────────────────────────────


@router.put("/mcp/profiles/{profile_id}/entries/{backend_id}")
async def upsert_entry_route(
    body: EntryUpsert,
    profile_id: str = _ID,
    backend_id: str = _ID,
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
    profile_id: str = _ID,
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if await db.get_profile(conn, user.login, profile_id) is None:
        raise HTTPException(status_code=404, detail="profil introuvable")
    if not await db.delete_profile_entry(conn, profile_id, backend_id):
        raise HTTPException(status_code=404, detail="entry introuvable")
