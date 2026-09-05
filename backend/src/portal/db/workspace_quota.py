"""Quota d'un forfait à la création d'un workspace : lecture de l'état, verdict délégué.

Ce module lit et branche ; il ne décide pas. Les règles vivent là où elles ont
toujours vécu — `billing.ownership.verifier_creation` pour une machine dédiée,
`billing.allocation.verifier_creation_pool` pour une machine du pool — et les
dupliquer ici en SQL ferait exister deux vérités qui divergeraient.

**Comptage résolu à chaque vérification, jamais mis en cache** : un compteur en
cache diverge du réel au premier workspace supprimé hors du chemin nominal, et
un quota faux est pire qu'un quota absent.

Le périmètre est celui du MODÈLE DE FACTURATION : une machine qui n'est ni
dédiée (ligne `host_ownership`) ni ouverte au pool (`hosts.accepts_mutualise`)
n'est gouvernée par aucun forfait — nœud enrôlé à la main, machine
d'administration — et la création y reste libre, sous les contrôles d'accès
existants. C'est aussi la réponse au « compte sans abonnement » : il crée
librement HORS du modèle, et se voit refuser SUR une machine du modèle, avec un
message qui dit quoi faire.
"""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.allocation import verifier_creation_pool
from ..billing.ownership import HostGuest, HostOwnership, verifier_creation
from ..billing.subscriptions import ETATS_OUVERTS
from .tables import (
    host_guests,
    host_ownership,
    hosts,
    subscription_hosts,
    subscriptions,
    workspaces,
)


async def verrouiller_creation(host_name: str, conn: AsyncConnection) -> None:
    """Sérialise les créations qui visent la même machine.

    Verrou consultatif TRANSACTIONNEL : il tombe au commit, et il est partagé
    par toutes les requêtes concurrentes — deux créations qui voient chacune la
    dernière place ne doivent pas passer toutes les deux. Le verrou par login de
    la route ne couvre pas ce cas : owner et invité sont deux comptes.
    """
    if not host_name:
        return
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('ws-quota:' || :h))"),
        {"h": host_name},
    )


async def verifier_quota_creation(login: str, host_name: str, conn: AsyncConnection) -> None:
    """Lève `QuotaDepasse` si ce compte ne peut pas créer un workspace de plus
    sur cette machine ; ne fait rien sinon.

    À appeler SOUS `verrouiller_creation`, dans la transaction qui écrira le
    workspace — un comptage lu puis écrit sans verrou laisse passer le
    dépassement qu'on cherche à empêcher.
    """
    if not host_name:
        return
    machine = (
        (
            await conn.execute(
                select(hosts.c.capacity_workspaces, hosts.c.accepts_mutualise).where(
                    hosts.c.name == host_name
                )
            )
        )
        .mappings()
        .first()
    )
    if machine is None:
        # Machine inconnue du parc : ce n'est pas au quota de la refuser — la
        # validation du host cible appartient au lifecycle.
        return

    propriete = (
        (await conn.execute(select(host_ownership).where(host_ownership.c.host_name == host_name)))
        .mappings()
        .first()
    )
    if propriete is not None:
        await _verifier_dedie(
            login, dict(propriete), machine["capacity_workspaces"], conn
        )
        return
    if machine["accepts_mutualise"]:
        await _verifier_pool(login, host_name, machine["capacity_workspaces"], conn)


async def _verifier_dedie(
    login: str, propriete: dict[str, object], capacite: int | None, conn: AsyncConnection
) -> None:
    """Machine dédiée : la règle est `ownership.verifier_creation`, en entier —
    droit d'accès (owner/invité), plafond machine/forfait, sous-limite d'invité.
    """
    host_name = str(propriete["host_name"])
    ownership = HostOwnership(
        host_name=host_name,
        owner_login=str(propriete["owner_login"]),
        hosting_type=propriete["hosting_type"],  # type: ignore[arg-type]
        offer_slug=propriete["offer_slug"],  # type: ignore[arg-type]
        # La capacité vit sur la MACHINE (migration 125) : elle est passée par
        # l'appelant, jamais relue d'une copie.
        capacity_workspaces=capacite,
        offer_max_workspaces=propriete["offer_max_workspaces"],  # type: ignore[arg-type]
    )
    lignes = (
        (await conn.execute(select(host_guests).where(host_guests.c.host_name == host_name)))
        .mappings()
        .all()
    )
    guests = [
        HostGuest(
            host_name=host_name,
            email=str(g["email"]),
            login=g["login"],
            allocated_workspaces=g["allocated_workspaces"],
            state=g["state"],
            token=str(g["token"]),
            expires_at=g["expires_at"],
        )
        for g in lignes
    ]
    utilisation = await _workspaces_par_login(host_name, conn)
    verifier_creation(ownership, guests, utilisation, login)


async def _verifier_pool(
    login: str, host_name: str, capacite: int | None, conn: AsyncConnection
) -> None:
    """Machine du pool : la part vient des abonnements OUVERTS du compte.

    Un abonnement résilié ne donne plus de place ; `echec_paiement` en donne
    encore — même fenêtre de grâce que le droit d'usage (`Subscription.ouvert`).
    """
    part = (
        await conn.execute(
            select(func.coalesce(func.sum(subscription_hosts.c.allocated_workspaces), 0))
            .select_from(
                subscription_hosts.join(
                    subscriptions, subscription_hosts.c.subscription_id == subscriptions.c.id
                )
            )
            .where(
                subscription_hosts.c.host_name == host_name,
                subscriptions.c.login == login,
                subscriptions.c.state.in_(sorted(ETATS_OUVERTS)),
            )
        )
    ).scalar_one()

    utilisation = await _workspaces_par_login(host_name, conn)
    verifier_creation_pool(
        host_name=host_name,
        part_allouee=int(part),
        mes_workspaces=utilisation.get(login, 0),
        capacite=capacite,
        utilises=sum(utilisation.values()),
    )


async def _workspaces_par_login(host_name: str, conn: AsyncConnection) -> dict[str, int]:
    """Workspaces posés sur CETTE machine, par compte — le réel, à l'instant."""
    stmt = (
        select(workspaces.c.login, func.count())
        .where(workspaces.c.host == host_name)
        .group_by(workspaces.c.login)
    )
    rows = (await conn.execute(stmt)).all()
    return {row_login: nombre for row_login, nombre in rows}
