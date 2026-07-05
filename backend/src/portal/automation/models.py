"""Modèles du moteur de règles : conditions (ET) → actions → enchaînement.

Sémantique : sur un événement déclencheur, chaque condition appelle sa sonde
(outil MCP) et teste le retour ; toutes doivent être vraies (ET logique, arrêt
au premier faux). Si la règle « matche », les actions sont exécutées dans
l'ordre (arrêt à la première erreur), puis la règle chaînée (next_rule) est
jouée à son tour. Les règles sont des données — déterministes, rejouables.
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
    None = service supprimé depuis : la règle est inopérante et le dit.

    Les valeurs string de `args` sont des gabarits : `{workspace}`, `{actor}`,
    `{event}` et `{subject[clé]}` sont substitués depuis l'événement.
    """

    model_config = ConfigDict(extra="forbid")

    service_id: str | None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Condition(BaseModel):
    """Une sonde + un test déterministe sur son retour.

    path : chemin d'extraction dans le résultat JSON ("a.b") ; appliqué à une
    liste, chaque segment projette la clé sur chaque élément. "" = résultat brut.
    value : gabarit, substitué avec le même contexte que les args.
    """

    model_config = ConfigDict(extra="forbid")

    service_id: str | None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    path: str = ""
    operator: Operator
    value: str = ""


class Rule(BaseModel):
    """Si toutes les `conditions` sont vraies, les `actions` sont exécutées
    dans l'ordre, puis la règle `next_rule` (id) est jouée le cas échéant.

    Aucune condition = toujours vrai (les actions courent à chaque événement).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    events: tuple[str, ...]
    conditions: tuple[Condition, ...] = ()
    actions: tuple[PrimitiveCall, ...]
    next_rule: str | None = None

    @field_validator("events")
    @classmethod
    def _known_events(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(v) - EVENT_TYPES
        if unknown:
            raise ValueError(f"types d'événements inconnus: {sorted(unknown)}")
        return v

    @field_validator("actions")
    @classmethod
    def _at_least_one_action(cls, v: tuple[PrimitiveCall, ...]) -> tuple[PrimitiveCall, ...]:
        if not v:
            raise ValueError("au moins une action est requise")
        return v
