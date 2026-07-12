"""Garde Bearer ASGI devant le mount /mcp.

Si le Bearer (apikey statique ou token OAuth) est absent/invalide/expiré, renvoie
un 401 HTTP + `WWW-Authenticate` pointant vers les métadonnées de ressource
protégée — ce qui amorce le flow OAuth côté client (Claude web). Sinon, laisse
passer vers l'app MCP (les handlers re-résolvent les droits fins).
"""
from __future__ import annotations

from typing import Any

from ..config.store import load_global
from ..db.engine import _get_engine
from .dispatch_common import extract_bearer, resolve_tenant


class BearerGate:
    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        # "lifespan" (démarrage/arrêt ASGI, pas une requête client) doit passer sans
        # auth — sinon l'app ne démarre jamais. Tout le reste (websocket compris) est
        # fail-closed explicite : le sous-app monté est HTTP uniquement aujourd'hui,
        # mais laisser passer un scope non-http sans vérification serait une brèche
        # dormante si un transport websocket était monté un jour (bug 029).
        if scope_type == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope_type != "http":
            await self._reject_non_http(scope_type, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        token = extract_bearer(headers)
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
        if tenant is None:
            await self._unauthorized(send)
            return
        await self._app(scope, receive, send)

    async def _reject_non_http(self, scope_type: str | None, receive: Any, send: Any) -> None:
        """Fail-closed pour tout scope non-http/lifespan (ex. websocket)."""
        if scope_type == "websocket":
            await receive()  # websocket.connect — doit être consommé avant de clore
            await send({"type": "websocket.close", "code": 4401})
            return
        # Type de scope ASGI inconnu : ne rien envoyer plutôt que de deviner un
        # protocole de rejet, mais ne jamais transmettre à l'app protégée.

    async def _unauthorized(self, send: Any) -> None:
        base = load_global().server.external_url.rstrip("/")
        www = f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", www.encode("latin-1")),
                    (b"content-type", b"application/json"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
