"""Routes proxy vers Open VSX : recherche, détail, readme.

Couche anti-corruption : le frontend ne voit que des DTOs normalisés
(PluginSummary, PluginDetail, PluginSearchResult), jamais le schéma brut.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from ..auth.rbac import UserInfo, require_user
from ..openvsx import OpenVsxClient, PluginDetail, PluginSearchResult

router = APIRouter(prefix="/plugins", tags=["plugins"])


def get_openvsx() -> OpenVsxClient:
    """Remplacée par dependency_overrides dans le lifespan (et dans les tests)."""
    raise NotImplementedError  # pragma: no cover


@router.get("/search", response_model=PluginSearchResult)
async def search_plugins(
    q: str | None = Query(default=None, min_length=1),
    sort: str = Query("relevance", pattern="^(relevance|popular|recent|rating)$"),
    offset: int = Query(0, ge=0),
    size: int = Query(24, ge=1, le=50),
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginSearchResult:
    try:
        return await client.search(q, sort=sort, offset=offset, size=size)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable") from exc


@router.get("/{namespace}/{name}/readme")
async def plugin_readme(
    namespace: str = Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"),
    name: str = Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"),
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> Response:
    """Route déclarée avant /{namespace}/{name} pour éviter le shadowing par FastAPI."""
    try:
        md = await client.readme(namespace, name)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Readme indisponible") from exc
    return Response(content=md, media_type="text/markdown; charset=utf-8")


@router.get("/{namespace}/{name}", response_model=PluginDetail)
async def plugin_detail(
    namespace: str = Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"),
    name: str = Path(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"),
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginDetail:
    try:
        return await client.detail(namespace, name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Plugin introuvable") from exc
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable") from exc
