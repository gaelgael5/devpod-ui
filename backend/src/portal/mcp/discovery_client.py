"""Client HTTP d'une source de découverte MCP (instance mcp-manager).

La source est configurée par son URL de base (ex. `https://mcp.yoops.org`) ;
l'API vit sous `/api/v1`. L'authentification passe par la clé du secret
`MCP_DISCOVERY` associé, en `Authorization: Bearer <key>`. `probe` valide
URL + clé via `/auth/me` ; `search` interroge le catalogue via `/search_mcp`.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class DiscoveryError(Exception):
    """Échec d'appel à une source de découverte (réseau, auth, HTTP)."""


def _api_base(url: str) -> str:
    """Base API `/api/v1` à partir de l'URL saisie (idempotent sur le suffixe)."""
    base = url.strip().rstrip("/")
    if not base:
        raise DiscoveryError("URL de source vide")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def probe(url: str, api_key: str) -> dict[str, Any]:
    """Valide connectivité + clé via `GET /api/v1/auth/me`.

    Retourne `{"ok": True, "name": ..., "email": ...}` si la clé est acceptée.
    Lève `DiscoveryError` (message lisible) sur échec réseau/HTTP/auth.
    """
    endpoint = f"{_api_base(url)}/auth/me"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(endpoint, headers=_headers(api_key))
    except httpx.HTTPError as exc:
        _log.info("discovery_probe_network_error", url=url, error=str(exc))
        raise DiscoveryError(f"Connexion impossible : {exc}") from exc

    if resp.status_code == 401:
        raise DiscoveryError("Clé refusée (401) — vérifie le secret sélectionné")
    if resp.status_code >= 400:
        raise DiscoveryError(f"Réponse HTTP {resp.status_code} de la source")

    try:
        data = resp.json()
    except ValueError as exc:
        raise DiscoveryError("Réponse non-JSON de la source") from exc

    return {
        "ok": True,
        "name": data.get("name") or data.get("pseudo"),
        "email": data.get("email"),
    }


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Sous-ensemble stable d'un item de catalogue affiché côté portail.

    On ne remonte que ce que l'UI de recherche exploite ; les champs d'install
    (`parameters`, `recipes`) seront ajoutés à l'étape « ajout ».
    """
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "description": raw.get("description") or "",
        "transport": raw.get("transport") or "",
        "category": raw.get("category"),
        "stars": raw.get("stars") or 0,
        "repo_status": raw.get("repo_status"),
        "source_url": raw.get("source_url") or "",
        "doc_url": raw.get("doc_url") or "",
    }


async def search(
    url: str, api_key: str, query: str, page: int = 1, per_page: int = 10
) -> dict[str, Any]:
    """Recherche dans le catalogue via `GET /api/v1/search_mcp`.

    Retourne `{"items": [...normalisés], "total", "page", "per_page"}`.
    Lève `DiscoveryError` (message lisible) sur échec réseau/HTTP/auth.
    """
    endpoint = f"{_api_base(url)}/search_mcp"
    params: dict[str, str | int] = {"q": query, "page": page, "per_page": per_page}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(endpoint, headers=_headers(api_key), params=params)
    except httpx.HTTPError as exc:
        _log.info("discovery_search_network_error", url=url, error=str(exc))
        raise DiscoveryError(f"Connexion impossible : {exc}") from exc

    if resp.status_code == 401:
        raise DiscoveryError("Clé refusée (401) — vérifie le secret sélectionné")
    if resp.status_code >= 400:
        raise DiscoveryError(f"Réponse HTTP {resp.status_code} de la source")

    try:
        data = resp.json()
    except ValueError as exc:
        raise DiscoveryError("Réponse non-JSON de la source") from exc

    items = data.get("items")
    if not isinstance(items, list):
        raise DiscoveryError("Réponse inattendue de la source (items manquants)")

    return {
        "items": [_normalize_item(it) for it in items if isinstance(it, dict)],
        "total": data.get("total", len(items)),
        "page": data.get("page", page),
        "per_page": data.get("per_page", per_page),
    }
