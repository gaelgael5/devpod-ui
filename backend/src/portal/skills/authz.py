"""Enforcement du routage des skills — LE point de décision d'autorisation.

L'epic pose que l'enforcement réel est le routage à la gateway, PAS le
filesystem (qui n'est qu'un cache). Ce module est la décision que la gateway
consulte avant de router une capability de skill. Il n'y a volontairement
AUCUN état ici : tout est dérivé des tables (grants, placements, délégations)
à chaque appel — révocation, pause, dérive de hash ou révocation de délégation
prennent effet à la requête suivante, sans nettoyage disque.

Double condition ANDée = deux kill-switches indépendants :
  (1) GRANT du principal : granted ∧ placement verified ∧
      installed_hash == approved_hash  (portal.db.skills)
  (2) DÉLÉGATION de l'acteur valide : agent → principal résolu
      (portal.db.delegations, fail closed)

`list_agent_effective_skills` combine déjà (1) restreint au principal de (2) ;
ce module en expose la décision UNITAIRE (une capability = une skill) et une
liste dédiée au routage, pour un point d'entrée unique et testable.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.delegations import list_agent_effective_skills


async def list_routable_skills(
    agent_id: str, workspace_id: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    """Skills que la gateway peut router pour cet agent dans ce workspace.

    Ensemble vide si la délégation est absente/expirée/révoquée (fail closed).
    Chaque entrée : skill_id, user_subject (principal), grant_id, placement_id.
    """
    return await list_agent_effective_skills(agent_id, workspace_id, conn)


async def is_skill_routable(
    agent_id: str, workspace_id: str, skill_id: str, conn: AsyncConnection
) -> bool:
    """Décision de routage d'UNE capability de skill (les deux conditions).

    True ssi l'acteur `agent_id`, on-behalf-of son principal délégant, dispose
    d'un grant `granted` sur `(skill_id, approved_hash)` avec un placement
    `verified` et hash concordant dans `workspace_id`. False dans tous les
    autres cas — c'est un refus, jamais une exception (fail closed).
    """
    routable = await list_agent_effective_skills(agent_id, workspace_id, conn)
    return any(entry["skill_id"] == skill_id for entry in routable)
