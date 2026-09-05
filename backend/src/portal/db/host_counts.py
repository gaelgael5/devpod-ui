"""Machines portées par hyperviseur, ventilées par nature et par vivacité.

Ce que l'écran Hyperviseurs affiche. Le rattachement machine → hyperviseur
passe par la PROVENANCE (`hosts.hypervisor`), jamais par un rapprochement de
noms de nœuds — c'est l'ambiguïté que la colonne existe pour supprimer. Une
machine sans provenance n'est attribuée à personne : elle remonte dans un
compte à part, que l'écran montre tel quel.

UNE seule requête agrégée pour toute la page : le décompte se relit à chaque
affichage, jamais une requête par ligne.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import host_health, hosts


class ComptesHyperviseur(BaseModel):
    """Ce qu'un hyperviseur porte, machines EN FONCTIONNEMENT par nature.

    « En fonctionnement » = sondée joignable. Une machine jamais sondée n'est
    NI active NI arrêtée — l'afficher d'un côté ou de l'autre serait un
    mensonge — elle a son propre compteur. Une machine prouvée injoignable ne
    compte nulle part : elle ne porte pas de charge.
    """

    model_config = ConfigDict(extra="forbid")

    workspaces: int = 0
    tests: int = 0
    ressources: int = 0
    #: `portail` et `autres`, agrégés : une machine portée reste une machine
    #: portée, quelle que soit sa destination — la laisser disparaître rendrait
    #: le total faux sans que rien ne le signale.
    autres: int = 0
    jamais_sondees: int = 0


class ComptesMachines(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Par nom d'hyperviseur — seulement ceux dont une machine porte la
    #: provenance. L'appelant zéro-remplit depuis le parc déclaré.
    par_hyperviseur: dict[str, ComptesHyperviseur] = Field(default_factory=dict)
    #: Machines sans provenance : enrôlées à la main, ou antérieures à la
    #: colonne. Personne ne se les attribue — un lien deviné est pire qu'un
    #: lien absent.
    sans_provenance: int = 0


#: usage → attribut de `ComptesHyperviseur`. Exhaustif sur les valeurs de
#: `HostConfig.usage` : une nouvelle destination non mappée tomberait dans
#: `autres` plutôt que de disparaître.
_NATURE = {"workspaces": "workspaces", "tests": "tests", "ressources": "ressources"}


async def machines_par_hyperviseur(conn: AsyncConnection) -> ComptesMachines:
    """Le décompte complet, en un aller-retour."""
    vivacite = host_health.c.reachable
    stmt = (
        select(hosts.c.hypervisor, hosts.c.usage, vivacite, func.count())
        .select_from(hosts.outerjoin(host_health, host_health.c.name == hosts.c.name))
        .group_by(hosts.c.hypervisor, hosts.c.usage, vivacite)
    )
    resultat = ComptesMachines()
    for provenance, usage, joignable, nombre in (await conn.execute(stmt)).all():
        if not provenance:
            resultat.sans_provenance += int(nombre)
            continue
        ligne = resultat.par_hyperviseur.setdefault(provenance, ComptesHyperviseur())
        if joignable is None:
            ligne.jamais_sondees += int(nombre)
        elif joignable:
            nature = _NATURE.get(usage, "autres")
            setattr(ligne, nature, getattr(ligne, nature) + int(nombre))
        # Prouvée injoignable : ne porte pas de charge, ne compte nulle part.
    return resultat
