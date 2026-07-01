"""Proxy applicatif VS Code — Option A.

Résout le problème WebSocket 1006 / CORS causé par Caddy forward_auth :
le browser JS ne renvoie pas les cookies sur les sous-requêtes fetch/WS,
donc forward_auth voit no_session → 302 → échec.

Solution : le portail Python proxy lui-même HTTP + WebSocket vers localhost:{host_port}
(le tunnel SSH déjà établi par service.py _start_port_forward).
Caddy ne fait plus qu'un rewrite /* → /vsproxy/* + reverse_proxy portal:8080.
L'authentification est vérifiée ici, une fois, via le cookie de session.
"""
from __future__ import annotations

import asyncio
import contextlib

import httpx
import structlog
import websockets
import websockets.exceptions
from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..config.store import load_global
from ..db.engine import _get_engine
from ..db.workspace_status import list_by_login_db

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["vscode-proxy"], include_in_schema=False)

# Headers HTTP hop-by-hop : ne doivent pas être transmis tels quels par un proxy.
_HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    ]
)


async def _resolve_host_port(login: str, ws_id_hint: str | None = None) -> int | None:
    """Retourne le host_port du workspace running de l'utilisateur.

    Préfère le workspace identifié par ws_id_hint si plusieurs sont running.
    """
    async with _get_engine().begin() as conn:
        all_ws = await list_by_login_db(login, conn)
    running = [w for w in all_ws if w.get("status") == "running" and w.get("host_port")]
    if not running:
        return None
    if ws_id_hint:
        ws = next((w for w in running if w.get("ws_id") == ws_id_hint), running[0])
    else:
        ws = running[0]
    return int(ws["host_port"])


def _session_login(request: Request) -> str | None:
    """Extrait le login depuis la session, ou None si non authentifié."""
    user_data = request.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        return None
    login = user_data.get("login")
    return str(login) if login else None


def _ws_id_hint_from_query(query_string: str) -> str | None:
    """Extrait un ws_id depuis ?folder=/workspaces/{ws_id}."""
    for part in query_string.split("&"):
        if part.startswith("folder="):
            folder = part[len("folder="):]
            segments = folder.strip("/").split("/")
            if len(segments) >= 2 and segments[0] == "workspaces":
                return segments[1]
    return None


@router.get("/vsproxy")
@router.get("/vsproxy/{path:path}")
async def vscode_http_proxy(request: Request, path: str = "") -> Response:
    """Proxy HTTP transparent vers OpenVSCode Server (assets, API REST).

    Vérifie la session via le cookie portal_session, résout le workspace
    actif de l'utilisateur, et proxy la requête vers localhost:{host_port}.
    """
    login = _session_login(request)
    if not login:
        external_url = (load_global().server.external_url or "").rstrip("/")
        if not external_url:
            # external_url non configuré : un redirect relatif /auth/login serait
            # réécrit par Caddy en /vsproxy/auth/login → boucle infinie.
            return Response(
                status_code=401,
                media_type="text/html",
                content=(
                    "<html><body><h1>Non authentifié</h1>"
                    "<p>Connectez-vous au portail d'abord, "
                    "puis revenez sur cette page.</p></body></html>"
                ),
            )
        return RedirectResponse(url=f"{external_url}/auth/login", status_code=302)

    qs = request.url.query
    ws_id_hint = _ws_id_hint_from_query(qs) if qs else None
    host_port = await _resolve_host_port(login, ws_id_hint)
    if host_port is None:
        return Response(status_code=503, content="No active workspace")

    upstream_path = f"/{path}" if path else "/"
    upstream_url = f"http://localhost:{host_port}{upstream_path}"
    if qs:
        upstream_url += f"?{qs}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    headers["host"] = f"localhost:{host_port}"

    body = await request.body()
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
            follow_redirects=False,
        )

    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    _log.debug(
        "vscode_http_proxy",
        login=login,
        path=upstream_path,
        status=upstream.status_code,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )


@router.websocket("/vsproxy/{path:path}")
async def vscode_ws_proxy(websocket: WebSocket, path: str) -> None:
    """Proxy WebSocket bidirectionnel vers OpenVSCode Server.

    Transmet les subprotocols négociés par l'upstream pour que VS Code
    (Language Server Protocol, Extension Host, etc.) fonctionne correctement.
    """
    from urllib.parse import urlparse as _urlparse

    from ..settings import get_settings

    # ── Validation d'origine (anti-CSWSH) ─────────────────────────────────────
    # Même pattern que workspace_ssh.py. En prod, les WS légitimes viennent soit
    # de vs_proxy_domain (VS Code ouvert dans le browser) soit du host de
    # external_url (navigations portail). Sans cette vérif, une page tierce
    # pourrait ouvrir un WS proxy en exploitant le cookie SameSite=Lax.
    if not get_settings().dev_mode:
        cfg = load_global()
        portal_host = _urlparse(cfg.server.external_url or "").netloc
        vs_host = cfg.server.vs_proxy_domain
        allowed_origins = {h for h in (portal_host, vs_host) if h}
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        origin_host = _urlparse(request_origin).netloc
        if not origin_host or origin_host not in allowed_origins:
            _log.warning(
                "vscode_ws_bad_origin",
                origin=request_origin,
                allowed=sorted(allowed_origins),
            )
            await websocket.close(code=4003, reason="Bad origin")
            return

    # Auth via session (avant accept pour pouvoir rejeter proprement).
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        await websocket.close(code=4001, reason="Not authenticated")
        return
    login = str(user_data.get("login", ""))
    if not login:
        await websocket.close(code=4001, reason="Invalid session")
        return

    host_port = await _resolve_host_port(login)
    if host_port is None:
        await websocket.close(code=4503, reason="No active workspace")
        return

    qs_bytes: bytes = websocket.scope.get("query_string", b"")
    upstream_path = f"/{path}"
    if qs_bytes:
        upstream_path += f"?{qs_bytes.decode()}"

    upstream_uri = f"ws://localhost:{host_port}{upstream_path}"

    # Subprotocols annoncés par le browser — à transmettre à l'upstream.
    raw_protocols = websocket.headers.get("sec-websocket-protocol", "")
    subprotocols: list[str] = (
        [p.strip() for p in raw_protocols.split(",") if p.strip()]
        if raw_protocols
        else []
    )

    _log.info("vscode_ws_proxy_open", login=login, path=upstream_path)

    try:
        async with websockets.connect(
            upstream_uri,
            subprotocols=subprotocols or None,  # type: ignore[arg-type]
        ) as upstream_ws:
            # Accepter le browser avec le subprotocol sélectionné par l'upstream.
            selected = upstream_ws.subprotocol
            await websocket.accept(subprotocol=selected)

            async def _browser_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        raw = msg.get("bytes")
                        text = msg.get("text")
                        if raw is not None:
                            await upstream_ws.send(raw)
                        elif text is not None:
                            await upstream_ws.send(text)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed, OSError):
                    pass
                except Exception as exc:
                    _log.warning(
                        "vscode_ws_browser_to_upstream_error",
                        exc_type=type(exc).__name__,
                    )

            async def _upstream_to_browser() -> None:
                try:
                    async for msg in upstream_ws:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed, OSError):
                    pass
                except Exception as exc:
                    _log.warning(
                        "vscode_ws_upstream_to_browser_error",
                        exc_type=type(exc).__name__,
                    )

            tasks = [
                asyncio.create_task(_browser_to_upstream()),
                asyncio.create_task(_upstream_to_browser()),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks, return_exceptions=True)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as exc:
        _log.warning(
            "vscode_ws_proxy_upstream_error",
            login=login,
            exc_type=type(exc).__name__,
        )
        with contextlib.suppress(Exception):
            await websocket.close(code=4502, reason="Upstream connection failed")
        return

    with contextlib.suppress(Exception):
        await websocket.close()

    _log.info("vscode_ws_proxy_closed", login=login, path=upstream_path)
