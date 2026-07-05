"""Modèles du moteur de règles : une règle = sonde → condition → action.

Sémantique : sur un événement déclencheur, la sonde (primitive MCP en lecture)
est appelée ; son retour est comparé via l'opérateur ; si la condition est
vraie, l'action (primitive MCP d'écriture) est appelée. Les règles sont des
données — déterministes, rejouables, idempotentes par construction.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..events.models import EVENT_TYPES

Operator = Literal["eq", "neq", "contains", "not_contains"]


class PrimitiveCall(BaseModel):
    """Appel d'un outil MCP résolu via le profil d'un service enregistré.

    `service_id` référence une ligne user_services de l'acteur ; `tool` est le
    nom namespacé exposé par le profil du service (ex. "docflow__create_block").
    None = service supprimé depuis (SET NULL) : la règle est inopérante.

    Les valeurs string de `args` sont des gabarits : `{workspace}`, `{actor}`,
    `{event}` et `{subject[clé]}` sont substitués depuis l'événement.
    """

    model_config = ConfigDict(extra="forbid")

    service_id: str | None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Condition(BaseModel):
    """Test déterministe du retour de la sonde.

    path : chemin d'extraction dans le résultat JSON ("a.b") ; appliqué à une
    liste, chaque segment projette la clé sur chaque élément. "" = résultat brut.
    value : gabarit, substitué avec le même contexte que les args.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = ""
    operator: Operator
    value: str


class Rule(BaseModel):
    """Si `condition(probe())` est vraie, `action` est exécutée."""

    model_config = ConfigDict(extra="forbid")

    name: str
    events: tuple[str, ...]
    probe: PrimitiveCall
    condition: Condition
    action: PrimitiveCall

    @field_validator("events")
    @classmethod
    def _known_events(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(v) - EVENT_TYPES
        if unknown:
            raise ValueError(f"types d'événements inconnus: {sorted(unknown)}")
        return v
