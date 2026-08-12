"""Rattachement user→instances Termix (`user_termix_instance`, spec 18 T4b).

N-N plafonnée à 3 (fallback/migration) : un user peut être servi par jusqu'à
`MAX_INSTANCES` serveurs Termix. Vide = héritage de l'instance `is_default`.
`resolve_instances_for_user` donne la liste effective consommée par le
provisioning fan-out (T5). La transaction est ouverte par l'appelant.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from . import termix_instance as ti
from .tables import user_termix_instance as _t

MAX_INSTANCES = 3


async def list_instance_ids(conn: AsyncConnection, login: str) -> list[str]:
    """Ids des instances rattachées à `login`, ordonnés."""
    stmt = select(_t.c.instance_id).where(_t.c.login == login).order_by(_t.c.instance_id)
    return [r[0] for r in (await conn.execute(stmt)).all()]


async def set_instances_for_user(
    conn: AsyncConnection, login: str, instance_ids: list[str]
) -> None:
    """Remplace l'ensemble des instances rattachées à `login` (diff minimal).

    Le plafond `MAX_INSTANCES` et l'existence des instances sont validés par
    l'appelant (route).
    """
    current = set(await list_instance_ids(conn, login))
    target = set(instance_ids)
    to_remove = current - target
    to_add = target - current
    if to_remove:
        await conn.execute(delete(_t).where(_t.c.login == login, _t.c.instance_id.in_(to_remove)))
    if to_add:
        await conn.execute(
            pg_insert(_t)
            .values([{"login": login, "instance_id": i} for i in sorted(to_add)])
            .on_conflict_do_nothing()
        )


async def resolve_instances_for_user(conn: AsyncConnection, login: str) -> list[dict[str, Any]]:
    """Instances Termix effectives d'un user (spec 18 T4b/T5).

    Instances explicitement rattachées (existantes) ; à défaut l'instance
    `is_default` seule ; sinon liste vide. Consommé par le provisioning fan-out.
    """
    ids = await list_instance_ids(conn, login)
    resolved = [inst for i in ids if (inst := await ti.get(conn, i)) is not None]
    if resolved:
        return resolved
    default = await ti.get_default(conn)
    return [default] if default is not None else []
