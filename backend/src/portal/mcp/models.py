from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

NAMESPACE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

Transport = Literal["streamable_http", "sse", "stdio"]


def _validate_namespace(v: str) -> str:
    if not NAMESPACE_RE.fullmatch(v):
        raise ValueError("namespace: minuscules/chiffres/underscore, 1 à 40 caractères")
    if "__" in v:
        raise ValueError("namespace: '__' est réservé au séparateur de namespacing")
    return v


def _validate_app_url(v: str) -> str:
    """URL web optionnelle de l'application : vide accepté, sinon http(s)."""
    if v and not (v.startswith("https://") or v.startswith("http://")):
        raise ValueError("app_url: doit être vide ou commencer par http:// ou https://")
    return v


class BackendCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    name: str
    url: str
    transport: Transport = "streamable_http"
    # URL web optionnelle de l'application (lien « ouvrir » dans la liste).
    app_url: str = ""

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return _validate_namespace(v)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url: doit commencer par http:// ou https://")
        return v

    @field_validator("app_url")
    @classmethod
    def _app_url(cls, v: str) -> str:
        return _validate_app_url(v)


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    description: str = ""
    storage_type: Literal["local", "harpocrate"]
    secret_value: str
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.fullmatch(v):
            raise ValueError("slug: minuscule initiale, [a-z0-9_-], 1 à 63 caractères")
        return v


class BackendUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    transport: Transport
    enabled: bool
    app_url: str = ""

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url: doit commencer par http:// ou https://")
        return v

    @field_validator("app_url")
    @classmethod
    def _app_url(cls, v: str) -> str:
        return _validate_app_url(v)


class ApikeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""


class GrantSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend_id: str
    # None = backend public (sans authentification) : aucune clé de service.
    backend_key_id: str | None = None
    expose_mode: Literal["all", "allowlist", "denylist"] = "all"
    expose: list[str] = []
    # False = service accordé mais temporairement désactivé (paramétrage conservé).
    enabled: bool = True
