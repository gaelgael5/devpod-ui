from __future__ import annotations

import structlog
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .auth.router import router as auth_router
from .routes.admin import router as admin_router
from .routes.me import router as me_router
from .routes.nodes import router as nodes_router
from .routes.recipes import router_admin as recipes_admin_router
from .routes.recipes import router_me as recipes_me_router
from .routes.recipes import router_public as recipes_public_router
from .routes.workspace_ops import router as workspace_ops_router
from .settings import get_settings

_log = structlog.get_logger(__name__)


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

    app = FastAPI(title="workspace-portal", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key or "dev-only-insecure-key",
        session_cookie="portal_session",
        https_only=not settings.dev_mode,
        same_site="lax",
        max_age=86400,
    )
    app.include_router(auth_router)
    app.include_router(me_router, prefix="/me")
    app.include_router(workspace_ops_router, prefix="/me")
    app.include_router(recipes_public_router)
    app.include_router(recipes_me_router, prefix="/me")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(nodes_router, prefix="/admin")
    app.include_router(recipes_admin_router, prefix="/admin")
    return app


app = create_app()
