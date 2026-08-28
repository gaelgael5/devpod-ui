"""État du parc mutualisé : qui a de la place, et combien.

Ce module lit ; il ne décide pas. Le verdict — assigner, ouvrir une machine, ne
rien faire — appartient à `billing.provisioning`, qui travaille sur ce que ce
module lui donne.

La règle des deux plafonds n'est pas réécrite ici : elle vit dans
`billing.ownership` (`limite_effective`, `capacite_restante`), et ce module s'y
adosse. La dupliquer en SQL ferait exister deux vérités qui divergeraient au
premier changement.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.ownership import HostOwnership, capacite_restante
from ..billing.provisioning import HostDisponible
from .tables import host_ownership, workspaces


async def _workspaces_par_host(conn: AsyncConnection) -> dict[str, int]:
    """Nombre de workspaces posés, par host.

    Un décompte global plutôt qu'une requête par machine : le pool se lit à
    chaque souscription, et une machine oubliée fausserait le verdict.
    """
    stmt = select(workspaces.c.host, func.count()).group_by(workspaces.c.host)
    rows = (await conn.execute(stmt)).all()
    return {host: nombre for host, nombre in rows if host}


async def pool_mutualise(conn: AsyncConnection) -> list[HostDisponible]:
    """Hosts mutualisés et leurs places restantes, triés par nom.

    `places_restantes` vaut `None` quand aucun plafond ne s'applique — profil de
    host sans `capacity_workspaces`. C'est un trou de configuration, pas une
    machine infinie, et le décideur le traite comme tel.
    """
    stmt = (
        select(host_ownership)
        .where(host_ownership.c.hosting_type == "mutualise")
        .order_by(host_ownership.c.host_name)
    )
    lignes = (await conn.execute(stmt)).mappings().all()
    if not lignes:
        return []

    utilises = await _workspaces_par_host(conn)
    pool: list[HostDisponible] = []
    for ligne in lignes:
        proprietaire = HostOwnership(
            host_name=ligne["host_name"],
            owner_login=ligne["owner_login"],
            hosting_type=ligne["hosting_type"],
            offer_slug=ligne["offer_slug"],
            capacity_workspaces=ligne["capacity_workspaces"],
            offer_max_workspaces=ligne["offer_max_workspaces"],
        )
        pool.append(
            HostDisponible(
                host_name=proprietaire.host_name,
                places_restantes=capacite_restante(
                    proprietaire, utilises.get(proprietaire.host_name, 0)
                ),
            )
        )
    return pool


async def a_deja_une_machine(owner_login: str, offer_slug: str, conn: AsyncConnection) -> bool:
    """Ce compte a-t-il déjà une machine provisionnée pour cette offre ?

    C'est le garde-fou de l'idempotence : `activation` arrive après
    `debut_essai` pour le même abonnement, et ne doit rien recréer. Le couple
    (propriétaire, offre) suffit à le dire — un même compte peut porter deux
    offres distinctes, chacune avec sa machine.
    """
    stmt = select(host_ownership.c.host_name).where(
        host_ownership.c.owner_login == owner_login,
        host_ownership.c.offer_slug == offer_slug,
    )
    return (await conn.execute(stmt)).first() is not None
