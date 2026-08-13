"""Page Utilisateurs admin — liste + rattachement aux instances Termix (spec 18 T4b).

- `GET /admin/users` : tous les users (login, email, display_name, instances Termix
  rattachées).
- `PUT /admin/users/{login}/termix-instances` : remplace l'ensemble des instances
  rattachées à un user (jusqu'à `MAX_INSTANCES`, vide = héritage du défaut).

Le sélecteur de host de cette page vit dans le routeur `host_grants` (T3). La vue
côté utilisateur (lecture) est servie par `GET /me/termix-instances` (routeur me).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..bastion.provision import (
    deprovision_user_from_instance,
    ensure_termix_account,
    provision_user_access,
)
from ..db import termix_instance as ti
from ..db import user_termix_instance as uti
from ..db.engine import get_conn
from ..db.user_config import list_users_db, user_exists_db

router = APIRouter(tags=["admin-users"])

_Admin = Annotated[UserInfo, Depends(require_admin)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


class TermixAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_ids: list[str]


@router.get("/users")
async def list_users(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    return await list_users_db(conn)


@router.put("/users/{login}/termix-instances")
async def set_termix_instances(
    login: str, body: TermixAssign, _: _Admin, conn: _Conn
) -> dict[str, list[str]]:
    if not await user_exists_db(login, conn):
        raise HTTPException(status_code=404, detail="utilisateur introuvable")
    ids = list(dict.fromkeys(body.instance_ids))  # dédoublonne en gardant l'ordre
    if len(ids) > uti.MAX_INSTANCES:
        raise HTTPException(
            status_code=422, detail=f"au plus {uti.MAX_INSTANCES} instances par utilisateur"
        )
    for i in ids:
        if await ti.get(conn, i) is None:
            raise HTTPException(status_code=422, detail=f"instance Termix introuvable : {i}")
    removed = set(await uti.list_instance_ids(conn, login)) - set(ids)
    await uti.set_instances_for_user(conn, login, ids)
    # Spec 18 T5 — « associer » suffit : (1) crée le compte Termix (username=email)
    # sur les instances rattachées + partage les hosts ; (2) sur les instances RETIRÉES,
    # supprime les hosts de l'user + son compte Termix (il ne peut plus s'y connecter).
    # Best-effort : les échecs sont remontés sans annuler l'association.
    warnings = await ensure_termix_account(conn, login, ids)
    warnings += await provision_user_access(conn, login)
    for inst_id in removed:
        warnings += await deprovision_user_from_instance(conn, login, inst_id)
    return {"instance_ids": await uti.list_instance_ids(conn, login), "termix_warnings": warnings}
