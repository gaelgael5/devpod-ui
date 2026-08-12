"""Couche DB de la portée user→host SSH (`user_host_grant`, spec 18 T3).

N-N pure entre `users.login` et `workspace_status.ws_id` (un host Termix = un
workspace SSH publié). Sert deux besoins :
- le sélecteur de host de la page Utilisateurs (T4) : lister/remplacer les hosts
  accordés à un user ;
- le provisioning (T5) : lister les users à qui partager un host donné.

La transaction est ouverte par l'appelant.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_host_grant as _t


async def grant(conn: AsyncConnection, login: str, ws_id: str) -> None:
    """Accorde `ws_id` à `login` (idempotent)."""
    stmt = pg_insert(_t).values(login=login, ws_id=ws_id).on_conflict_do_nothing()
    await conn.execute(stmt)


async def revoke(conn: AsyncConnection, login: str, ws_id: str) -> bool:
    """Retire l'accès ; True si une ligne a été supprimée."""
    result = await conn.execute(delete(_t).where(_t.c.login == login, _t.c.ws_id == ws_id))
    return bool(result.rowcount)


async def is_granted(conn: AsyncConnection, login: str, ws_id: str) -> bool:
    stmt = select(_t.c.login).where(_t.c.login == login, _t.c.ws_id == ws_id)
    return (await conn.execute(stmt)).first() is not None


async def list_hosts_for_user(conn: AsyncConnection, login: str) -> list[str]:
    """`ws_id` des hosts accordés à `login`, ordonnés."""
    stmt = select(_t.c.ws_id).where(_t.c.login == login).order_by(_t.c.ws_id)
    return [r[0] for r in (await conn.execute(stmt)).all()]


async def list_users_for_host(conn: AsyncConnection, ws_id: str) -> list[str]:
    """`login` des users à qui `ws_id` est accordé, ordonnés (consulté par T5)."""
    stmt = select(_t.c.login).where(_t.c.ws_id == ws_id).order_by(_t.c.login)
    return [r[0] for r in (await conn.execute(stmt)).all()]


async def set_hosts_for_user(conn: AsyncConnection, login: str, ws_ids: list[str]) -> None:
    """Remplace l'ensemble des hosts accordés à `login` par `ws_ids` (diff minimal)."""
    current = set(await list_hosts_for_user(conn, login))
    target = set(ws_ids)
    to_add = target - current
    to_remove = current - target
    if to_remove:
        await conn.execute(delete(_t).where(_t.c.login == login, _t.c.ws_id.in_(to_remove)))
    if to_add:
        await conn.execute(
            pg_insert(_t)
            .values([{"login": login, "ws_id": w} for w in sorted(to_add)])
            .on_conflict_do_nothing()
        )
