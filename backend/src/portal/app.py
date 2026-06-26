from __future__ import annotations

import asyncio
import contextlib
import socket as _socket
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth.router import router as auth_router
from .mcp.monitor import monitor_loop
from .mcp.server import build_server as _build_mcp_server
from .routes.admin import router as admin_router
from .routes.certificates import router_admin as certs_admin_router
from .routes.certificates import router_me as certs_me_router
from .routes.mcp import router as mcp_router
from .routes.me import router as me_router
from .routes.nodes import router as nodes_router
from .routes.oauth import router as oauth_router
from .routes.plugins import get_openvsx
from .routes.plugins import router as plugins_router
from .routes.profile_sources import router_admin as profile_sources_admin_router
from .routes.profiles import get_repo as get_profile_repo
from .routes.profiles import router as profiles_router
from .routes.profiles import router_admin as profiles_admin_router
from .routes.proxmox import router as proxmox_router
from .routes.recipe_sources import router_admin as recipe_sources_admin_router
from .routes.recipes import router_admin as recipes_admin_router
from .routes.recipes import router_me as recipes_me_router
from .routes.recipes import router_public as recipes_public_router
from .routes.secrets import router_admin as secrets_admin_router
from .routes.secrets import router_me as secrets_me_router
from .routes.ssh_proxy import router as ssh_proxy_router
from .routes.static import router as static_router
from .routes.test_vm import router as test_vm_router
from .routes.vault import router as vault_router
from .routes.workspace_ops import _get_service
from .routes.workspace_ops import router as workspace_ops_router
from .routes.workspace_sessions import router as workspace_sessions_router
from .routes.workspace_ssh import router as workspace_ssh_router
from .settings import get_settings, resolve_cookie_domain
from .spa import should_serve_spa

_log = structlog.get_logger(__name__)

# L'environnement Docker n'a pas de routage IPv6. urllib3 (requests/harpocrate)
# tente IPv6 en premier et échoue sans fallback. On réordonne getaddrinfo pour
# que l'IPv4 soit toujours essayé en premier quand la famille est non spécifiée.
_orig_getaddrinfo = _socket.getaddrinfo


def _prefer_ipv4(*args: object, **kwargs: object) -> object:
    results = _orig_getaddrinfo(*args, **kwargs)  # type: ignore[arg-type]
    family = args[2] if len(args) > 2 else kwargs.get("family", 0)
    if family == 0:
        ipv4 = [r for r in results if r[0] == _socket.AF_INET]
        if ipv4:
            return ipv4 + [r for r in results if r[0] != _socket.AF_INET]
    return results


_socket.getaddrinfo = _prefer_ipv4  # type: ignore[assignment]

_SPA_INDEX = Path("static") / "index.html"
_NO_CACHE = "no-cache, no-store, must-revalidate"


class SPAMiddleware(BaseHTTPMiddleware):
    """Sert index.html pour les requêtes de navigation navigateur vers des routes frontend.

    Sans ce middleware, les routes API comme GET /admin/hypervisors prenaient la priorité
    sur le routeur React, renvoyant du JSON brut lors d'un rechargement de page.
    Critère : requête GET dont le Accept inclut text/html (navigation browser)
    et dont le chemin n'a pas d'extension (pas un asset JS/CSS/image).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        accept = request.headers.get("Accept", "")
        if should_serve_spa(request.method, request.url.path, accept) and _SPA_INDEX.is_file():
            return FileResponse(_SPA_INDEX, headers={"Cache-Control": _NO_CACHE})

        return await call_next(request)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from .db.engine import _get_engine
    from .db.global_config import warm_global_cache
    from .db.profiles import AsyncProfileRepository
    from .openvsx import OpenVsxClient, OpenVsxSettings

    settings_obj = get_settings()
    if settings_obj.database_url:
        from .db.migration import run_migrations

        await run_migrations(settings_obj.database_url)
        async with _get_engine().begin() as conn:
            await warm_global_cache(conn)
            from .secrets.system import ensure_system_user

            await ensure_system_user(conn)

        # Pas de synchro automatique des recettes : c'est l'admin qui choisit quoi
        # synchroniser, via POST /admin/recipes/sync.

    with contextlib.suppress(Exception):
        await _get_service().reconcile_port_forwards()

    profile_repo = AsyncProfileRepository()
    app.dependency_overrides[get_profile_repo] = lambda: profile_repo
    async with httpx.AsyncClient(headers={"User-Agent": "devpod-ui/1.0"}) as http:
        client = OpenVsxClient(OpenVsxSettings(), http)
        app.dependency_overrides[get_openvsx] = lambda: client
        async with app.state.mcp_session_manager.run():
            _monitor_task: asyncio.Task[None] | None = None
            if settings_obj.database_url:
                _monitor_task = asyncio.create_task(
                    monitor_loop(settings_obj.mcp_monitor_interval_s)
                )
            try:
                yield
            finally:
                if _monitor_task is not None:
                    _monitor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await _monitor_task


def create_app() -> FastAPI:
    settings = get_settings()

    if not settings.session_secret_key:
        if settings.dev_mode:
            _log.warning(
                "session_secret_key_empty_dev_mode",
                msg="SESSION_SECRET_KEY not set — using insecure fallback (dev mode only)",
            )
        else:
            raise RuntimeError(
                "SESSION_SECRET_KEY must be set via environment variable or .env file. "
                "Starting without a session secret key is not allowed in production."
            )

    if not settings.portal_vault_kek:
        if settings.dev_mode:
            _log.warning(
                "portal_vault_kek_missing",
                msg="PORTAL_VAULT_KEK not set — vault feature disabled (dev mode only)",
            )
        else:
            raise RuntimeError(
                "PORTAL_VAULT_KEK must be set in .env. "
                "Generate with: openssl rand -hex 32"
            )

    app = FastAPI(title="workspace-portal", version="0.1.0", lifespan=_lifespan)

    from mcp.server.fastmcp.server import StreamableHTTPASGIApp

    # _mcp_server (index 0) est la référence bas-niveau non utilisée ici ; seul le
    # gestionnaire de sessions est monté et stocké dans app.state pour le lifespan.
    _mcp_session_manager = _build_mcp_server()[1]
    app.mount("/mcp", StreamableHTTPASGIApp(_mcp_session_manager))
    app.state.mcp_session_manager = _mcp_session_manager

    # Starlette insère chaque middleware en tête de liste (prepend).
    # Ordre d'exécution requête : SessionMiddleware → SPAMiddleware → Router.
    # SPAMiddleware court-circuite le routeur API pour les navigations browser.
    app.add_middleware(SPAMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key or "dev-only-insecure-key",
        session_cookie="portal_session",
        https_only=not settings.dev_mode,
        same_site="lax",
        max_age=86400,
        # Partage le cookie avec les workspaces (forward_auth Caddy) — COOKIE_DOMAIN
        # prime sur BASE_DOMAIN quand portail et workspaces diffèrent d'ancêtre.
        domain=resolve_cookie_domain(settings.cookie_domain, settings.base_domain),
    )
    app.include_router(auth_router)
    app.include_router(me_router, prefix="/me")
    app.include_router(workspace_ops_router, prefix="/me")
    app.include_router(workspace_sessions_router, prefix="/me")
    app.include_router(test_vm_router, prefix="/me")
    app.include_router(plugins_router)
    app.include_router(recipes_public_router)
    app.include_router(recipes_me_router, prefix="/me")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(nodes_router, prefix="/admin")
    app.include_router(proxmox_router, prefix="/admin")
    app.include_router(recipes_admin_router, prefix="/admin")
    app.include_router(recipe_sources_admin_router, prefix="/admin")
    app.include_router(profile_sources_admin_router, prefix="/admin")
    app.include_router(ssh_proxy_router, prefix="/admin")
    app.include_router(workspace_ssh_router, prefix="/me")
    app.include_router(profiles_router)
    app.include_router(profiles_admin_router, prefix="/admin")
    app.include_router(vault_router)
    app.include_router(certs_me_router, prefix="/me")
    app.include_router(certs_admin_router, prefix="/admin")
    app.include_router(secrets_me_router, prefix="/me")
    app.include_router(secrets_admin_router, prefix="/admin")
    app.include_router(mcp_router, prefix="/me")
    app.include_router(oauth_router)  # racine : /.well-known/* et /oauth/*
    # static_router en dernier : son catch-all /{full_path:path} ne doit pas
    # intercepter les routes API enregistrées avant lui.
    app.include_router(static_router)

    return app


app = create_app()
