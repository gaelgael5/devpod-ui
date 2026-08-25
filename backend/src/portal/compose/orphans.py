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

from collections.abc import Iterable

from .models import ComposeDeployment


def select_orphans(
    deployments: Iterable[ComposeDeployment],
    known_node_ids: Iterable[str],
) -> list[ComposeDeployment]:
    """Déploiements pointant vers un nœud absent de l'inventaire.

    `known_node_ids` doit être l'inventaire COMPLET des hosts, pas les seules
    cibles éligibles au déploiement : un host bien vivant mais exclu des
    déploiements (usage « autres ») n'est pas un orphelin, et le purger
    supprimerait des services qui tournent.
    """
    connus = set(known_node_ids)
    return [d for d in deployments if d.node_id not in connus]
