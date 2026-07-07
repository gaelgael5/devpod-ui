"""Modèles des types d'agents workspace (spec 35).

Un type d'agent décrit le fichier de configuration MCP attendu par une famille
d'agents (Claude Code, Gemini CLI…) : template Jinja du contenu, nom du fichier
généré sur le host, chemin cible dans le conteneur (templatable).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

# replace : fichier dédié MCP, rendu complet. merge : fichier partagé avec les
# réglages utilisateur, le template rend un fragment `portal-*` fusionné (35b).
AgentMode = Literal["replace", "merge"]

AGENT_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")
# Nom de fichier simple : dotfile accepté, jamais de séparateur de chemin.
FILENAME_RE = re.compile(r"^\.?[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_filename(v: str) -> str:
    """Nom de fichier simple : pas de '/', pas de '..', pas de composant vide."""
    if not FILENAME_RE.fullmatch(v):
        raise ValueError(
            "filename: nom simple requis (dotfile accepté), pas de séparateur de chemin"
        )
    return v


def validate_target_path(v: str) -> str:
    """Chemin cible dans le conteneur, templatable ({{ home }}, {{ project_root }}).

    Le rendu final est revalidé au provisioning ; ici on rejette d'emblée toute
    remontée de chemin.
    """
    if not v.strip():
        raise ValueError("target_path: valeur vide interdite")
    if "\\" in v:
        raise ValueError("target_path: séparateur '\\' interdit")
    if ".." in v.split("/"):
        raise ValueError("target_path: composant '..' interdit")
    return v


class _AgentTypeFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    filename: str
    template: str
    target_path: str

    @field_validator("label", "template")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("valeur vide interdite")
        return v

    @field_validator("filename")
    @classmethod
    def _filename(cls, v: str) -> str:
        return validate_filename(v)

    @field_validator("target_path")
    @classmethod
    def _target_path(cls, v: str) -> str:
        return validate_target_path(v)


class AgentTypeCreate(_AgentTypeFields):
    id: str
    enabled: bool = True
    mode: AgentMode = "replace"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not AGENT_ID_RE.fullmatch(v):
            raise ValueError("id: slug ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$ requis")
        return v


class AgentTypeUpdate(_AgentTypeFields):
    enabled: bool
    # None = inchangé : un client qui ne connaît pas encore le champ ne doit
    # jamais écraser la valeur existante (contrat db.update_agent_type).
    mode: AgentMode | None = None
