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

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..bastion.provision import (
    deprovision_user_from_instance,
    ensure_termix_account,
    provision_user_access,
)
from ..bastion.servers import sync_server_hosts_for_user
from ..db import termix_instance as ti
from ..db import user_termix_instance as uti
from ..db.engine import _get_engine, get_conn
from ..db.user_config import list_users_db, user_exists_db

_log = structlog.get_logger(__name__)
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
async def set_termix_instances(login: str, body: TermixAssign, _: _Admin) -> dict[str, list[str]]:
    ids = list(dict.fromkeys(body.instance_ids))  # dédoublonne en gardant l'ordre
    # 1) Validation + écriture de l'association, COMMITTÉE avant tout provisioning.
    #    Le provisioning (sync) lit les instances sur sa PROPRE connexion → il doit voir
    #    l'état committé, sinon course / état faux (clics rapides).
    async with _get_engine().begin() as conn:
        if not await user_exists_db(login, conn):
            raise HTTPException(status_code=404, detail="utilisateur introuvable")
        if len(ids) > uti.MAX_INSTANCES:
            raise HTTPException(
                status_code=422, detail=f"au plus {uti.MAX_INSTANCES} instances par utilisateur"
            )
        for i in ids:
            if await ti.get(conn, i) is None:
                raise HTTPException(status_code=422, detail=f"instance Termix introuvable : {i}")
        removed = set(await uti.list_instance_ids(conn, login)) - set(ids)
        await uti.set_instances_for_user(conn, login, ids)

    # 2) Effets de bord SYNCHRONES (spec 18 T5) : le PUT ne répond qu'à la FIN du
    #    provisioning → l'IHM garde le bouton désactivé + spinner jusqu'ici, ce qui
    #    empêche les clics concurrents et la course. Comptes Termix + partage sur les
    #    instances rattachées ; suppression sur les instances RETIRÉES ; puis serveurs
    #    (hosts d'infra / ressources / tests). Best-effort : un échec Termix ne fait pas
    #    échouer le PUT (l'association est déjà persistée) — tout est remonté en warnings.
    warnings: list[str] = []
    async with _get_engine().connect() as conn:
        for coro in (
            ensure_termix_account(conn, login, ids),
            provision_user_access(conn, login),
            *(deprovision_user_from_instance(conn, login, i) for i in removed),
        ):
            try:
                warnings += await coro
            except Exception as exc:
                _log.warning("termix_sideeffect_failed", login=login, error=str(exc))
                warnings.append(f"Termix : {exc}")
    try:
        await sync_server_hosts_for_user(login)
    except Exception as exc:
        _log.warning("termix_server_sync_failed", login=login, error=str(exc))
        warnings.append(f"Termix serveurs : {exc}")

    async with _get_engine().connect() as conn:
        instance_ids = await uti.list_instance_ids(conn, login)
    return {"instance_ids": instance_ids, "termix_warnings": warnings}
