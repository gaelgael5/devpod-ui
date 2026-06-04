from __future__ import annotations

import httpx
import structlog

_log = structlog.get_logger(__name__)


def _build_route(
    route_id: str, match_host: str, upstream: str, verify_uri: str
) -> dict[str, object]:
    """Construit la configuration de route Caddy.

    Structure : forward_auth (§F-33 fail-closed) AVANT reverse_proxy.
    L'en-tête Cookie est transmis à l'endpoint de vérification pour valider
    la session OIDC avant de proxyfier vers le workspace.
    """
    return {
        "@id": route_id,
        "match": [{"host": [match_host]}],
        "handle": [
            {
                "handler": "forward_auth",
                "uri": verify_uri,
                "copy_headers": ["Cookie"],
            },
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": upstream}],
            },
        ],
        "terminal": True,
    }


class CaddyClient:
    """Client pour l'API admin Caddy — gestion dynamique des routes workspace.

    Utilise PATCH pour les mises à jour idempotentes (route existante par @id),
    et POST pour la création si la route n'existe pas encore (404 sur PATCH).
    Jamais de rechargement de configuration (§F-31).
    """

    def __init__(
        self,
        admin_api: str,
        http_client: httpx.AsyncClient,
        verify_uri: str,
    ) -> None:
        self._admin_api = admin_api.rstrip("/")
        self._client = http_client
        self._verify_uri = verify_uri

    async def upsert_route(
        self,
        route_id: str,
        match_host: str,
        upstream: str,
    ) -> None:
        """Crée ou met à jour une route Caddy pour un workspace.

        Essaie d'abord PATCH (mise à jour idempotente par @id).
        Si 404 (route absente), fait un POST pour la créer.

        Args:
            route_id: identifiant unique de la route (ex: "ws-alice-myapp").
            match_host: hostname à matcher (ex: "ws-alice-myapp.dev.yoops.org").
            upstream: adresse upstream dial (ex: "192.168.1.50:41000").
        """
        route = _build_route(
            route_id=route_id,
            match_host=match_host,
            upstream=upstream,
            verify_uri=self._verify_uri,
        )
        resp = await self._client.patch(
            f"{self._admin_api}/id/{route_id}",
            json=route,
        )
        if resp.status_code == 404:
            resp = await self._client.post(
                f"{self._admin_api}/config/apps/http/servers/srv0/routes",
                json=route,
            )
        resp.raise_for_status()
        _log.info("caddy_route_upserted", route_id=route_id, upstream=upstream)

    async def remove_route(self, route_id: str) -> None:
        """Supprime une route Caddy par son identifiant @id.

        Un 404 est silencieux (la route n'existe peut-être plus déjà).
        Toute autre erreur (5xx…) lève une HTTPStatusError.

        Args:
            route_id: identifiant de la route à supprimer.
        """
        resp = await self._client.delete(f"{self._admin_api}/id/{route_id}")
        if resp.status_code not in (200, 404):
            resp.raise_for_status()
        _log.info("caddy_route_removed", route_id=route_id)
