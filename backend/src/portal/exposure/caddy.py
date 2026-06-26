from __future__ import annotations

import httpx
import structlog

_log = structlog.get_logger(__name__)


def internal_verify_uri(portal_host: str, listen: str) -> str:
    """URI du forward_auth Caddy, en interne sur le réseau Docker.

    Caddy interroge le portail directement (ex. http://portal:8080/auth/caddy/verify)
    plutôt que via l'URL publique : pas d'aller-retour Cloudflare ni de boucle réseau.
    Le port est extrait de `listen` (ex. "0.0.0.0:8080").
    """
    port = listen.rsplit(":", 1)[-1]
    return f"http://{portal_host}:{port}/auth/caddy/verify"


def _build_route(
    route_id: str,
    match_host: str,
    upstream: str,
    verify_uri: str,
    require_auth: bool = True,
) -> dict[str, object]:
    """Construit la configuration de route Caddy.

    En mode production (require_auth=True) : forward_auth (§F-33 fail-closed)
    AVANT reverse_proxy — la session OIDC est vérifiée avant tout accès workspace.
    En mode dev (require_auth=False) : reverse_proxy seul (pas de TLS/auth).
    """
    handlers: list[dict[str, object]] = []
    if require_auth:
        handlers.append(
            {
                "handler": "forward_auth",
                "uri": verify_uri,
                "copy_headers": ["Cookie"],
            }
        )
    handlers.append(
        {
            "handler": "reverse_proxy",
            "upstreams": [{"dial": upstream}],
            "flush_interval": -1,
            "transport": {
                "protocol": "http",
                "read_buffer_size": 0,
            },
        }
    )
    return {
        "@id": route_id,
        "match": [{"host": [match_host]}],
        "handle": handlers,
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
        server_name: str = "srv0",
        require_auth: bool = True,
    ) -> None:
        self._admin_api = admin_api.rstrip("/")
        self._client = http_client
        self._verify_uri = verify_uri
        self._server_name = server_name
        self._require_auth = require_auth

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
            require_auth=self._require_auth,
        )
        resp = await self._client.patch(
            f"{self._admin_api}/id/{route_id}",
            json=route,
        )
        if resp.status_code == 404:
            resp = await self._client.post(
                f"{self._admin_api}/config/apps/http/servers/{self._server_name}/routes",
                json=route,
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            _log.error("caddy_route_upsert_failed", route_id=route_id, status=resp.status_code)
            raise
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
