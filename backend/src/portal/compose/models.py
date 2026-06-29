"""Modèles de la galerie docker-compose (spec 26 §4 + cadrage)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$")

ComposeParamType = Literal["string", "number", "bool", "enum", "port", "secret"]
TemplateSource = Literal["user", "builtin", "imported"]
DeploymentStatus = Literal["created", "running", "partial", "stopped", "error"]


def validate_slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise ValueError(f"slug invalide: {value!r} (attendu ^[a-z0-9][a-z0-9-]{{0,40}}[a-z0-9]$)")
    return value


class ComposeParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str | None = None
    type: ComposeParamType
    default: str | None = None
    required: bool = False
    options: list[str] | None = None
    secret_ref_hint: str | None = None


class ComposeTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    version: str
    compose_content: str
    parameters: list[ComposeParam] = Field(default_factory=list)
    source: TemplateSource = "user"
    message_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ComposeDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    template_version: str
    node_id: str
    owner_login: str
    env_values: dict[str, str] = Field(default_factory=dict)
    host_ports: list[int] = Field(default_factory=list)
    status: DeploymentStatus = "created"
    last_error: str | None = None
    message_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
