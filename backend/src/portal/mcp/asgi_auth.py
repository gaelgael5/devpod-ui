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
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
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
