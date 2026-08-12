"""Portée user→host SSH — endpoints admin (spec 18 T3).

Alimente et filtre le sélecteur de host de la page Utilisateurs (T4) :
- `GET /admin/ssh-hosts` : l'univers des hosts SSH publiés (workspaces avec un
  `ssh_port`), sélectionnables.
- `GET/PUT /admin/users/{login}/host-grants` : lire / remplacer l'ensemble des
  hosts accordés à un user. Le provisioning (T5) consulte ces grants pour ne
  partager un host qu'aux users accordés.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db import user_host_grant as grants
from ..db.engine import get_conn
from ..db.user_config import user_exists_db
from ..db.workspace_status import list_ssh_hosts_db

router = APIRouter(tags=["host-grants"])

_Admin = Annotated[UserInfo, Depends(require_admin)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


class HostGrantsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hosts: list[str]


@router.get("/ssh-hosts")
async def list_ssh_hosts(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    """Univers des hosts SSH publiés (ws_id, login propriétaire, node, port)."""
    return await list_ssh_hosts_db(conn)


@router.get("/users/{login}/host-grants")
async def get_host_grants(login: str, _: _Admin, conn: _Conn) -> dict[str, list[str]]:
    if not await user_exists_db(login, conn):
        raise HTTPException(status_code=404, detail="utilisateur introuvable")
    return {"hosts": await grants.list_hosts_for_user(conn, login)}


@router.put("/users/{login}/host-grants")
async def set_host_grants(
    login: str, body: HostGrantsBody, _: _Admin, conn: _Conn
) -> dict[str, list[str]]:
    if not await user_exists_db(login, conn):
        raise HTTPException(status_code=404, detail="utilisateur introuvable")
    known = {h["ws_id"] for h in await list_ssh_hosts_db(conn)}
    unknown = [w for w in body.hosts if w not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"hosts inconnus : {unknown}")
    await grants.set_hosts_for_user(conn, login, body.hosts)
    return {"hosts": await grants.list_hosts_for_user(conn, login)}
