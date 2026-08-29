"""Ce qu'un abonnement a obtenu, machine par machine.

Ce module écrit et lit ; il ne décide pas. Les règles — quota du forfait,
capacité de la machine — vivent dans `billing.allocation`, qui travaille sur ce
que ce module lui donne. Les dupliquer en SQL ferait exister deux vérités qui
divergeraient au premier changement.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.allocation import Part
from .tables import subscription_hosts


async def rattacher(
    subscription_id: str,
    host_name: str,
    allocated_workspaces: int | None,
    conn: AsyncConnection,
) -> None:
    """Pose ou met à jour la part de cet abonnement sur cette machine.

    `None` = machine dédiée : aucun plafond commercial, la capacité physique
    gouverne seule.

    L'écriture est un upsert, et ce n'est pas une commodité : un webhook rejoué
    est la norme. Insérer une seconde ligne doublerait la consommation de quota
    d'un abonné qui n'a rien demandé de plus.
    """
    stmt = pg_insert(subscription_hosts).values(
        subscription_id=subscription_id,
        host_name=host_name,
        allocated_workspaces=allocated_workspaces,
    )
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["subscription_id", "host_name"],
            set_={"allocated_workspaces": stmt.excluded.allocated_workspaces},
        )
    )


async def detacher(subscription_id: str, host_name: str, conn: AsyncConnection) -> None:
    """Retire le rattachement — la place redevient disponible pour le pool."""
    await conn.execute(
        delete(subscription_hosts).where(
            subscription_hosts.c.subscription_id == subscription_id,
            subscription_hosts.c.host_name == host_name,
        )
    )


async def parts_de(subscription_id: str, conn: AsyncConnection) -> list[Part]:
    """Parts mutualisées de cet abonnement, triées par machine.

    Les machines dédiées n'y figurent pas : elles n'ont pas de part. Pour les
    obtenir, voir `machines_de`.
    """
    stmt = (
        select(subscription_hosts.c.host_name, subscription_hosts.c.allocated_workspaces)
        .where(
            subscription_hosts.c.subscription_id == subscription_id,
            subscription_hosts.c.allocated_workspaces.is_not(None),
        )
        .order_by(subscription_hosts.c.host_name)
    )
    lignes = (await conn.execute(stmt)).all()
    return [Part(host_name=nom, allocated_workspaces=part) for nom, part in lignes]


async def machines_de(subscription_id: str, conn: AsyncConnection) -> list[str]:
    """Toutes les machines de cet abonnement, dédiées comprises."""
    stmt = (
        select(subscription_hosts.c.host_name)
        .where(subscription_hosts.c.subscription_id == subscription_id)
        .order_by(subscription_hosts.c.host_name)
    )
    return [nom for (nom,) in (await conn.execute(stmt)).all()]


async def places_promises(host_name: str, conn: AsyncConnection) -> int:
    """Places déjà vendues sur cette machine, tous abonnements confondus.

    C'est un engagement, pas une occupation : une place promise et pas encore
    utilisée reste indisponible pour un autre abonné. Compter les workspaces
    réellement posés à la place ferait revendre la même place deux fois.
    """
    stmt = select(func.coalesce(func.sum(subscription_hosts.c.allocated_workspaces), 0)).where(
        subscription_hosts.c.host_name == host_name
    )
    return int((await conn.execute(stmt)).scalar_one())
