"""Déploiements dont le nœud n'existe plus.

Une machine détruite emporte ses conteneurs, mais ses lignes de déploiement
restaient en base. Elles ressortaient telles quelles sur la machine suivante qui
portait le même nom, présentées comme « en cours d'exécution » alors que plus
rien ne tournait — trois services affichés sur `host-test-106-1` pour un seul
conteneur réel.

La fuite est colmatée à la source (la suppression d'une VM de test purge ses
lignes), mais les lignes déjà orphelines, elles, ne disparaîtront pas toutes
seules : d'où la purge explicite.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from .models import ComposeDeployment


def select_orphans(
    deployments: Iterable[ComposeDeployment],
    known_node_ids: Iterable[str],
    node_created_at: Mapping[str, datetime] | None = None,
) -> list[ComposeDeployment]:
    """Déploiements qui ne peuvent pas tourner là où ils prétendent tourner.

    Deux cas, tous deux décidables sans interroger la machine :

    1. **Le nœud n'existe plus.** `known_node_ids` doit être l'inventaire
       COMPLET des hosts, pas les seules cibles éligibles au déploiement : un
       host bien vivant mais exclu des déploiements (usage « autres ») n'est pas
       un orphelin, et le purger supprimerait des services qui tournent.

    2. **Le nœud est plus jeune que le déploiement.** Un nom de machine se
       réemploie : une VM de test supprimée puis recréée sous le même nom fait
       réapparaître les lignes de l'ancienne. Un déploiement antérieur à la
       machine qui le porte n'a jamais pu y être installé — c'est le seul
       critère qui les distingue, le nom ne suffit pas.

    Une date manquante (des deux côtés) ne conclut rien : on ne purge pas.
    """
    connus = set(known_node_ids)
    naissances = node_created_at or {}

    def orphelin(d: ComposeDeployment) -> bool:
        if d.node_id not in connus:
            return True
        naissance = naissances.get(d.node_id)
        return naissance is not None and d.created_at is not None and d.created_at < naissance

    return [d for d in deployments if orphelin(d)]
