"""Sources de découverte MCP — `/me/mcp/discovery-sources`.

Configure les instances mcp-manager (URL + secret MCP_DISCOVERY) qu'on
interroge pour rechercher des services MCP. Étape 2 : lister / créer / supprimer
une source et **tester** (probe) la connectivité + la clé avant enregistrement.
La valeur de la clé n'est jamais renvoyée ni stockée ici — seule sa référence
(slug de secret) l'est.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp_discovery as db
from ..db.engine import get_conn
from ..mcp.discovery_client import DiscoveryError, probe, search
from ..secrets.service import SecretNotFound, VaultLocked, reveal_secret

router = APIRouter(tags=["mcp-discovery"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_SourceId = Annotated[int, Path(ge=1)]


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


class SourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    slug: str
    url: str
    secret_slug: str = ""

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("label: 1 à 100 caractères")
        return v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug: minuscules, chiffres, - ou _ (1 à 63 caractères)")
        return v

    @field_validator("secret_slug")
    @classmethod
    def _secret_slug(cls, v: str) -> str:
        if v and not _SLUG_RE.fullmatch(v):
            raise ValueError("secret_slug invalide")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https?://", v) or len(v) > 300:
            raise ValueError("url: http(s) requis, max 300 caractères")
        return v.rstrip("/")


class ProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    secret_slug: str = ""


@router.get("/mcp/discovery-sources")
async def list_sources_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await db.list_sources(user.login, conn)


@router.post("/mcp/discovery-sources", status_code=201)
async def create_source_route(
    body: SourceBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    try:
        return await db.create_source(
            user.login, body.label, body.slug, body.url, body.secret_slug, conn
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"slug '{body.slug}' déjà utilisé") from exc


@router.delete("/mcp/discovery-sources/{source_id}", status_code=204)
async def delete_source_route(
    source_id: _SourceId,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_source(user.login, source_id, conn):
        raise HTTPException(status_code=404, detail="source introuvable")


async def _resolve_key(login: str, session_id: str, secret_slug: str, conn: AsyncConnection) -> str:
    """Valeur claire du secret, ou chaîne vide si aucun secret n'est associé."""
    if not secret_slug:
        return ""
    try:
        return await reveal_secret(login, session_id, secret_slug, conn)
    except VaultLocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SecretNotFound as exc:
        raise HTTPException(status_code=404, detail="secret introuvable") from exc


@router.post("/mcp/discovery-sources/probe")
async def probe_source_route(
    body: ProbeBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    key = await _resolve_key(user.login, _sid(request), body.secret_slug, conn)
    try:
        return await probe(body.url, key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mcp/discovery-sources/{source_id}/search")
async def search_source_route(
    source_id: _SourceId,
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=50)] = 10,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    source = await db.get_source(user.login, source_id, conn)
    if source is None:
        raise HTTPException(status_code=404, detail="source introuvable")
    key = await _resolve_key(user.login, _sid(request), source["secret_slug"], conn)
    try:
        return await search(source["url"], key, q, page, per_page)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
