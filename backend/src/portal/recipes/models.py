# backend/src/portal/recipes/models.py
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_RECIPE_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")
_SECRET_PATH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$")
_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class RecipeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "string"
    default: str = ""
    description: str = ""


class SecretRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    env: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not _SECRET_PATH_RE.fullmatch(v):
            raise ValueError(f"secret path {v!r} contient des caractères invalides")
        return v

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if not _ENV_VAR_RE.fullmatch(v):
            raise ValueError(f"env var name {v!r} must match ^[A-Z][A-Z0-9_]{{0,63}}$")
        return v


class MemoryVolumeMappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str  # chemin absolu dans le conteneur (ex. /home/vscode/.claude)


class MemoryVolumeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # suffixe du nom Docker volume (ex. "claude-code" → "{ws_id}-claude-code")
    optional: bool = True  # si True, l'utilisateur choisit d'activer ; si False, toujours actif
    mapping: MemoryVolumeMappingSpec


class RecipeMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["install", "start"] = "install"
    version: str = "1.0.0"
    description: str = ""
    options: dict[str, RecipeOption] = Field(default_factory=dict)
    requires_secrets: list[SecretRef] = Field(default_factory=list)
    # Liste de GUIDs (key) des recipes à installer avant celle-ci.
    # Auto-incluses même si non sélectionnées par l'utilisateur.
    installs_after: list[str] = Field(default_factory=list)
    memory_volume: MemoryVolumeSpec | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _RECIPE_ID_RE.fullmatch(v):
            raise ValueError(f"id {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _UUID_RE.fullmatch(v):
            raise ValueError(f"key {v!r} must be a valid UUID")
        return v.lower()

    @field_validator("installs_after", mode="before")
    @classmethod
    def validate_installs_after(cls, v: list[str]) -> list[str]:
        for item in v:
            if not _UUID_RE.fullmatch(item):
                raise ValueError(
                    f"installs_after item {item!r} must be a valid UUID (recipe key)"
                )
        return [i.lower() for i in v]

    @field_validator("requires_secrets", mode="before")
    @classmethod
    def normalize_secret_refs(cls, v: list[Any]) -> list[dict[str, str]]:
        """Accepte string courte ou dict explicite."""
        result = []
        for item in v:
            if isinstance(item, str):
                env = item.upper().replace("/", "_").replace("-", "_")
                result.append({"path": item, "env": env})
            else:
                result.append(item)
        return result

    @classmethod
    def from_yaml(cls, path: str | Path) -> RecipeMeta:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
