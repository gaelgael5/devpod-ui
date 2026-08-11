"""Arbre de règle d'un automate (champ JSONB `automation.tree`).

Une règle = une liste de blocs **récursifs**. Chaque bloc porte un filtre
(arbre ET/OU imbriqué de feuilles « appel + évaluation JSONPath »), des appels
nommés, et des blocs enfants. Parcours en profondeur : filtre → s'il passe,
appels puis enfants ; sinon le sous-arbre est sauté et le bloc frère suivant
continue. La réponse JSON de chaque appel est rangée dans un dictionnaire sous
son `name` : les templates aval y accèdent par `{<name>.chemin.vers.champ}`.

Le schéma est LA validation unique : routes API et primitives MCP valident via
`RuleTree.model_validate`, le runner re-parse le JSONB au moment d'exécuter.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .filter_eval import OPERATORS

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# Nom d'un appel : racine de variable de template ({name.champ...}) → pas de point.
_CALL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class TreeHeader(BaseModel):
    """En-tête d'un appel/filtre : `value` XOR `secret_ref` (les deux None = stub).

    `secret_ref` = référence vault résolue à l'exécution (`${system://slug}` ou
    `${vault://…}`) ; `value_prefix` est concaténé devant (ex. « Bearer »).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | None = None
    secret_ref: str | None = None
    value_prefix: str = ""
    required: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def _value_xor_secret(self) -> TreeHeader:
        if self.value is not None and self.secret_ref is not None:
            raise ValueError(f"en-tête {self.name!r} : value et secret_ref exclusifs")
        return self


class TreeCall(BaseModel):
    """Appel HTTP nommé ; sa réponse JSON est exposée sous `name` aux blocs aval."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    http_method: str
    body_template: str | None = None
    # En-têtes propres à l'appel (pré-remplis depuis l'opération du contrat).
    headers: list[TreeHeader] = Field(default_factory=list)
    # Métadonnées d'édition (opération de contrat choisie dans l'IHM).
    contract_ref: str | None = None
    operation_id: str | None = None

    @field_validator("name")
    @classmethod
    def _name_is_template_root(cls, v: str) -> str:
        if not _CALL_NAME_RE.fullmatch(v):
            raise ValueError(
                f"nom d'appel invalide : {v!r} (lettres/chiffres/_, sans point, max 64)"
            )
        return v

    @field_validator("http_method")
    @classmethod
    def _method_known(cls, v: str) -> str:
        if v not in HTTP_METHODS:
            raise ValueError(f"méthode HTTP invalide : {v!r}")
        return v

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url d'appel vide")
        return v


class TreeFilterLeaf(BaseModel):
    """Feuille de filtre : appel HTTP + évaluation JSONPath/opérateur sur la réponse."""

    model_config = ConfigDict(extra="forbid")

    url: str
    http_method: str = "GET"
    body: str | None = None
    jsonpath: str
    operator: str
    expected: str | None = None
    # En-têtes propres au filtre (pré-remplis depuis l'opération du contrat).
    headers: list[TreeHeader] = Field(default_factory=list)
    contract_ref: str | None = None
    operation_id: str | None = None

    @field_validator("http_method")
    @classmethod
    def _method_known(cls, v: str) -> str:
        if v not in HTTP_METHODS:
            raise ValueError(f"méthode HTTP invalide : {v!r}")
        return v

    @field_validator("operator")
    @classmethod
    def _operator_known(cls, v: str) -> str:
        if v not in OPERATORS:
            raise ValueError(f"opérateur inconnu : {v!r} (attendus : {', '.join(OPERATORS)})")
        return v

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url de filtre vide")
        return v


class TreeFilterGroup(BaseModel):
    """Groupe ET/OU d'un arbre de filtres (imbrication libre)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["and", "or"]
    items: list[TreeFilterNode] = Field(min_length=1)


# Union structurelle : une feuille n'a pas de champ `op`, un groupe n'a que
# `op` + `items` — extra="forbid" rend la résolution non ambiguë.
TreeFilterNode = TreeFilterGroup | TreeFilterLeaf


class TreeBlock(BaseModel):
    """Bloc récursif : filtre (porte) → appels → blocs enfants."""

    model_config = ConfigDict(extra="forbid")

    label: str = ""
    filter: TreeFilterNode | None = None
    calls: list[TreeCall] = Field(default_factory=list)
    blocks: list[TreeBlock] = Field(default_factory=list)


class RuleTree(BaseModel):
    """Racine du champ `automation.tree`."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    blocks: list[TreeBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def _call_names_unique(self) -> RuleTree:
        seen: set[str] = set()
        for call in iter_calls(self.blocks):
            if call.name in seen:
                raise ValueError(f"nom d'appel dupliqué dans la règle : {call.name!r}")
            seen.add(call.name)
        return self


def iter_calls(blocks: list[TreeBlock]) -> list[TreeCall]:
    """Tous les appels de l'arbre, ordre de parcours en profondeur."""
    out: list[TreeCall] = []
    for block in blocks:
        out.extend(block.calls)
        out.extend(iter_calls(block.blocks))
    return out


EMPTY_TREE: dict[str, object] = {"version": 1, "blocks": []}


TreeFilterGroup.model_rebuild()
TreeBlock.model_rebuild()
