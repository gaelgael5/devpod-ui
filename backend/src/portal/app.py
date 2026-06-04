from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .auth.router import router as auth_router
from .routes.me import router as me_router
from .settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="workspace-portal", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key or "dev-only-insecure-key",
        session_cookie="portal_session",
        https_only=False,
        same_site="lax",
        max_age=86400,
    )
    app.include_router(auth_router)
    app.include_router(me_router, prefix="/me")
    return app


app = create_app()
