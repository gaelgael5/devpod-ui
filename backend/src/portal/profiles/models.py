from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Scope = Literal["shared", "user"]

# Référence d'image OCI : [registre[:port]/]chemin[:tag][@sha256:…]. Volontairement
# stricte (pas d'espace, jamais de '-' en tête : la valeur finit dans un
# devcontainer.json puis dans une ligne de commande docker côté nœud).
_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(:[0-9]{1,5})?"  # registre (host[:port]) ou 1er segment
    r"(/[a-z0-9][a-z0-9._-]*)*"  # segments du chemin
    r"(:[A-Za-z0-9_][A-Za-z0-9._-]{0,127})?"  # tag
    r"(@sha256:[a-f0-9]{64})?$"  # digest
)


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w\s\-+.]{1,80}$")
    description: str = ""
    # Image de base du devcontainer — vide = image par défaut du portail. Permet
    # de partir d'une image outillée (ex. mcr.microsoft.com/devcontainers/python)
    # et de ne cocher des recettes que pour les manques.
    image: str = ""
    extensions: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("image")
    @classmethod
    def validate_image(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        if len(v) > 400 or not _IMAGE_RE.fullmatch(v):
            raise ValueError(f"invalid OCI image reference: {v!r}")
        return v


class Profile(ProfileBody):
    slug: str
    scope: Scope

    def to_customizations(self) -> dict[str, Any]:
        return {"vscode": {"extensions": self.extensions, "settings": self.settings}}


class ProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    scope: Scope
    name: str
    description: str
    image: str = ""
    extension_count: int
    editable: bool
    gallery_source: str | None = None
