"""Page Utilisateurs admin — liste + rattachement à une instance Termix (spec 18 T4).

- `GET /admin/users` : tous les users (login, email, display_name, instance Termix).
- `PUT /admin/users/{login}/termix-instance` : rattache un user à une instance
  (ou `null` pour hériter du défaut). Résolution effective : `resolve_for_user`.

Le sélecteur de host de cette page vit dans le routeur `host_grants` (T3).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db import termix_instance as ti
from ..db.engine import get_conn
from ..db.user_config import list_users_db, set_user_termix_instance_db, user_exists_db

router = APIRouter(tags=["admin-users"])

_Admin = Annotated[UserInfo, Depends(require_admin)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


class TermixAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str | None = None


@router.get("/users")
async def list_users(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    return await list_users_db(conn)


@router.put("/users/{login}/termix-instance")
async def set_termix_instance(
    login: str, body: TermixAssign, _: _Admin, conn: _Conn
) -> dict[str, str | None]:
    if not await user_exists_db(login, conn):
        raise HTTPException(status_code=404, detail="utilisateur introuvable")
    if body.instance_id is not None and await ti.get(conn, body.instance_id) is None:
        raise HTTPException(status_code=422, detail="instance Termix introuvable")
    await set_user_termix_instance_db(login, body.instance_id, conn)
    return {"instance_id": body.instance_id}
