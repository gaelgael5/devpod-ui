"""DTOs API de la galerie compose."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..compose.models import ComposeParam, DeploymentStatus, TemplateSource


class TemplateCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    tags: list[str] = []
    version: str
    compose_content: str
    parameters: list[ComposeParam] = []
    source: TemplateSource = "user"
    message_key: str | None = None


class TemplateUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    tags: list[str] = []
    version: str
    compose_content: str
    parameters: list[ComposeParam] = []
    source: TemplateSource = "user"
    message_key: str | None = None


class DeploymentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    node_id: str
    name: str  # slug du déploiement
    env_values: dict[str, str] = {}


class DeploymentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    template_version: str
    node_id: str
    owner_login: str
    host_ports: list[int]
    status: DeploymentStatus
    last_error: str | None = None
