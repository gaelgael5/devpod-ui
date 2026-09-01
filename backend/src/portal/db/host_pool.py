"""État du parc mutualisé : qui a de la place, et combien.

Ce module lit ; il ne décide pas. Le verdict — assigner, ouvrir une machine, ne
rien faire — appartient à `billing.provisioning`, qui travaille sur ce que ce
module lui donne.

La règle des places libres n'est pas réécrite ici : elle vit dans
`billing.allocation.places_libres`. La dupliquer en SQL ferait exister deux
vérités qui divergeraient au premier changement.

**Le pool se lit sur la MACHINE, pas sur la propriété.** La migration 117 l'a
posé et l'écrit noir sur blanc : `hosts.accepts_mutualise` dit quelles machines
le pool peut remplir, et *une machine mutualisée n'a pas de propriétaire*. Ce
module interrogeait encore `host_ownership`, dont la clé primaire est le nom de
la machine et dont `owner_login` est NOT NULL — c'est-à-dire la définition d'une
machine DÉDIÉE. S'y adosser obligeait à inventer un propriétaire à une machine
qui, par construction, n'en a pas.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.allocation import places_libres
from ..billing.provisioning import HostDisponible
from .subscription_hosts import machines_de, places_promises_par_host
from .tables import hosts, workspaces


async def _workspaces_par_host(conn: AsyncConnection) -> dict[str, int]:
    """Nombre de workspaces posés, par host.

    Un décompte global plutôt qu'une requête par machine : le pool se lit à
    chaque souscription, et une machine oubliée fausserait le verdict.
    """
    stmt = select(workspaces.c.host, func.count()).group_by(workspaces.c.host)
    rows = (await conn.execute(stmt)).all()
    return {host: nombre for host, nombre in rows if host}


async def pool_mutualise(conn: AsyncConnection) -> list[HostDisponible]:
    """Hosts ouverts au pool et leurs places restantes, triés par nom.

    `places_restantes` vaut `None` quand la machine ne déclare pas de capacité.
    C'est un trou de configuration, pas une machine infinie, et le décideur le
    traite comme tel.
    """
    stmt = (
        select(hosts.c.name, hosts.c.capacity_workspaces)
        .where(hosts.c.accepts_mutualise.is_(True))
        .order_by(hosts.c.name)
    )
    lignes = (await conn.execute(stmt)).all()
    if not lignes:
        return []

    # Deux décomptes globaux, pas deux requêtes par machine.
    promises = await places_promises_par_host(conn)
    utilises = await _workspaces_par_host(conn)
    return [
        HostDisponible(
            host_name=nom,
            places_restantes=places_libres(
                capacite, promises.get(nom, 0), utilises.get(nom, 0)
            ),
        )
        for nom, capacite in lignes
    ]


async def a_deja_une_machine(subscription_id: str, conn: AsyncConnection) -> bool:
    """Cet ABONNEMENT a-t-il déjà sa machine ?

    Garde-fou de l'idempotence : `activation` arrive après `debut_essai` pour le
    même abonnement, et ne doit rien recréer.

    La clé est l'abonnement, et **pas** le couple (compte, offre) — c'est ce que
    dit la migration 118, et l'ancienne clé disait le contraire : un même compte
    peut souscrire deux fois la même offre, ce qui est parfaitement légitime, et
    le couple les confondait. La seconde souscription était alors considérée
    comme déjà provisionnée et ne recevait rien, en silence.

    Limiter l'offre de bienvenue à une par compte est une règle d'ÉLIGIBILITÉ,
    évaluée à la souscription, et surtout pas une exception glissée ici : le
    provisioning n'a pas à connaître les règles de vente.
    """
    return bool(await machines_de(subscription_id, conn))
