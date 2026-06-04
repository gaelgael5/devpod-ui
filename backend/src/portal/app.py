from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

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
    return app


app = create_app()
