from __future__ import annotations

from urllib.parse import urlparse

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


def internal_verify_workspace_uri(portal_host: str, listen: str) -> str:
    """URI du forward_auth pour le proxy VS Code à sous-domaine fixe.

    Résout dynamiquement le workspace actif de l'utilisateur et retourne
    X-Workspace-Upstream pour que Caddy puisse router vers le bon port.
    """
    port = listen.rsplit(":", 1)[-1]
    return f"http://{portal_host}:{port}/auth/caddy/verify-workspace"


def _ws_proxy(upstream: str) -> dict[str, object]:
    """reverse_proxy vers le workspace (streaming activé pour les WebSockets VS Code)."""
    return {
        "handler": "reverse_proxy",
        "upstreams": [{"dial": upstream}],
        "flush_interval": -1,
        "transport": {"protocol": "http", "read_buffer_size": 0},
    }


def _forward_auth_handler(verify_uri: str) -> dict[str, object]:
    """Équivalent JSON de la directive Caddyfile `forward_auth` (§F-33 fail-closed).

    `forward_auth` n'est PAS un handler Caddy : c'est un reverse_proxy vers le
    serveur d'auth, réécrit en GET sur le chemin de vérification, dont la réponse
    non-2xx est renvoyée telle quelle (accès refusé) et la 2xx laisse passer la
    requête via next (en recopiant le Cookie). Structure issue de `caddy adapt`.

    Le proxy workspace doit être dans la même liste handle que ce handler :
    quand handle_response [2xx] complète sans écrire de réponse, Caddy appelle
    next.ServeHTTP → le handler suivant s'exécute (ex. _ws_proxy). C'est le
    pattern Caddyfile `forward_auth` + `reverse_proxy` enchaînés.
    """
    parsed = urlparse(verify_uri)
    handle_response_routes: list[dict[str, object]] = [
        {"handle": [{"handler": "headers", "request": {"delete": ["Cookie"]}}]},
        {
            "handle": [
                {
                    "handler": "headers",
                    "request": {
                        "set": {"Cookie": ["{http.reverse_proxy.header.Cookie}"]}
                    },
                }
            ],
            "match": [
                {"not": [{"vars": {"{http.reverse_proxy.header.Cookie}": [""]}}]}
            ],
        },
    ]
    return {
        "handler": "reverse_proxy",
        "upstreams": [{"dial": parsed.netloc}],
        "rewrite": {"method": "GET", "uri": parsed.path},
        "headers": {
            "request": {
                "set": {
                    "X-Forwarded-Method": ["{http.request.method}"],
                    "X-Forwarded-Uri": ["{http.request.uri}"],
                },
                # Retire l'upgrade WebSocket de la sous-requête d'auth : sinon le
                # reverse_proxy tente un handshake WS vers /auth/caddy/verify (endpoint
                # HTTP) qui le rejette (403), cassant le WS du workspace. Le proxy
                # workspace suivant, lui, conserve l'upgrade.
                "delete": ["Connection", "Upgrade"],
            }
        },
        "handle_response": [
            {
                "match": {"status_code": [2]},
                "routes": handle_response_routes,
            }
        ],
    }


def _build_route(
    route_id: str,
    match_host: str,
    upstream: str,
    verify_uri: str,
    require_auth: bool = True,
) -> dict[str, object]:
    """Construit la configuration de route Caddy.

    En production (require_auth=True) : un subroute enchaîne l'auth (§F-33) puis le
    reverse_proxy workspace. En dev (require_auth=False) : reverse_proxy seul.
    """
    if not require_auth:
        handle: list[dict[str, object]] = [_ws_proxy(upstream)]
    else:
        handle = [
            {
                "handler": "subroute",
                "routes": [
                    {"handle": [_forward_auth_handler(verify_uri), _ws_proxy(upstream)]}
                ],
            }
        ]
    return {
        "@id": route_id,
        "match": [{"host": [match_host]}],
        "handle": handle,
        "terminal": True,
    }


def _build_vs_proxy_route(
    route_id: str,
    match_host: str,
    verify_uri: str,
    host_port: int,
) -> dict[str, object]:
    """Route Caddy pour le proxy VS Code à sous-domaine fixe (vs_proxy_domain).

    Utilise le même pattern que _build_route : forward_auth + _ws_proxy chaînés
    dans le même handle list. Quand handle_response [2xx] complète sans réponse,
    Caddy appelle next → _ws_proxy s'exécute. Pas de placeholder dynamique :
    l'upstream est inscrit dans la route au moment du workspace_up.
    """
    upstream = f"portal:{host_port}"
    return {
        "@id": route_id,
        "match": [{"host": [match_host]}],
        "handle": [
            {
                "handler": "subroute",
                "routes": [
                    {"handle": [_forward_auth_handler(verify_uri), _ws_proxy(upstream)]}
                ],
            }
        ],
        "terminal": True,
    }


def _build_vs_portal_route(
    route_id: str,
    match_host: str,
    portal_upstream: str,
) -> dict[str, object]:
    """Route Caddy pour le proxy VS Code applicatif (sans forward_auth).

    Réécrit /* → /vsproxy/* et proxy vers le portail Python.
    L'authentification est gérée dans le handler /vsproxy/* du portail.
    Le flush_interval=-1 active le streaming sans bufferisation (WebSocket + SSE).
    """
    return {
        "@id": route_id,
        "match": [{"host": [match_host]}],
        "handle": [
            {
                "handler": "subroute",
                "routes": [
                    {
                        "handle": [
                            {
                                "handler": "rewrite",
                                "uri": "/vsproxy{uri}",
                            },
                            {
                                "handler": "reverse_proxy",
                                "upstreams": [{"dial": portal_upstream}],
                                "flush_interval": -1,
                                "transport": {
                                    "protocol": "http",
                                    "read_buffer_size": 0,
                                },
                            },
                        ]
                    }
                ],
            }
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

    async def upsert_vs_proxy_route(
        self, match_host: str, verify_uri: str, host_port: int
    ) -> None:
        """Crée ou met à jour la route VS proxy unique (@id="vs-proxy").

        Args:
            match_host: hostname à matcher (ex: "vs-dev.yoops.org").
            verify_uri: URI interne du forward_auth verify-workspace.
            host_port: port du port-forward portal→workspace (ex: 40000).
        """
        route_id = "vs-proxy"
        route = _build_vs_proxy_route(
            route_id=route_id,
            match_host=match_host,
            verify_uri=verify_uri,
            host_port=host_port,
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
            _log.error(
                "caddy_vs_proxy_route_failed", match_host=match_host, status=resp.status_code
            )
            raise
        _log.info("caddy_vs_proxy_route_upserted", match_host=match_host)

    async def upsert_vs_portal_route(
        self, match_host: str, portal_upstream: str
    ) -> None:
        """Crée ou met à jour la route VS Code proxy applicatif (@id="vs-portal").

        Contrairement à upsert_vs_proxy_route, cette route ne contient pas de
        forward_auth : l'authentification est gérée dans le portail Python via
        le cookie de session. Caddy se contente de réécrire /* → /vsproxy/* et
        de proxy vers portal_upstream.

        Args:
            match_host: hostname à matcher (ex: "vs-dev.yoops.org").
            portal_upstream: adresse dial du portail (ex: "portal:8080").
        """
        route_id = "vs-portal"
        route = _build_vs_portal_route(
            route_id=route_id,
            match_host=match_host,
            portal_upstream=portal_upstream,
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
            _log.error(
                "caddy_vs_portal_route_failed",
                match_host=match_host,
                status=resp.status_code,
            )
            raise
        _log.info("caddy_vs_portal_route_upserted", match_host=match_host)

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
