"""Client HTTP d'une source de découverte MCP (instance mcp-manager).

La source est configurée par son URL de base (ex. `https://mcp.yoops.org`) ;
l'API vit sous `/api/v1`. L'authentification passe par la clé du secret
`MCP_DISCOVERY` associé, en `Authorization: Bearer <key>`. Étape 2 : `probe`
valide URL + clé via `/auth/me`. La recherche sera ajoutée à l'étape 3.
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
