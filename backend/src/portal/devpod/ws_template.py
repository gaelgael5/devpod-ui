"""Application d'un template de workspace — le merge, à un seul endroit.

Précédence décidée au cadrage : **explicite > template > défaut**. La route
REST « from-template » (UI figée : nom + repo) et l'outil MCP
`workspace_create` (surcharges permises aux agents) passent tous deux ici —
deux chemins de création qui mergeraient différemment seraient deux
comportements à déboguer.
"""

from __future__ import annotations

from typing import Any

from ..config.models import WorkspaceSpec, WorkspaceTemplate

#: Champs du preset transposés tels quels vers la spec quand l'appelant ne les
#: fournit pas explicitement. `branch` est traité à part (il a un défaut métier).
_CHAMPS_PRESET = (
    "recipes",
    "start_recipes",
    "init_recipes",
    "recipe_volumes",
    "default_start",
    "agents",
    "profile",
    "memory_limit",
    "ssh_key",
    "ide",
    "env",
)


def composer_spec(
    template: WorkspaceTemplate,
    *,
    name: str,
    source: str,
    surcharges: dict[str, Any] | None = None,
) -> WorkspaceSpec:
    """La `WorkspaceSpec` d'une création depuis un template.

    `surcharges` : champs de `WorkspaceSpec` fournis explicitement par
    l'appelant (API/MCP) — ils priment sur le preset. `name` et `source`
    appartiennent toujours à l'utilisateur ; le template ne peut pas les
    porter, par construction du modèle.
    """
    surcharges = dict(surcharges or {})
    valeurs: dict[str, Any] = {"name": name, "source": source}
    preset = template.spec
    for champ in _CHAMPS_PRESET:
        if champ in surcharges:
            valeurs[champ] = surcharges.pop(champ)
        else:
            valeurs[champ] = getattr(preset, champ)
    valeurs["branch"] = surcharges.pop("branch", None) or preset.branch or "dev"
    # Le reste des surcharges (host, git_credential…) passe tel quel : la
    # validation appartient à WorkspaceSpec, pas au merge.
    valeurs.update(surcharges)
    return WorkspaceSpec.model_validate(valeurs)
