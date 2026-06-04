from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from pathlib import Path

import structlog
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config.store import _data_root, ensure_user_dir
from ..settings import get_settings
from .oidc import OIDCClient, OIDCError
from .rbac import UsernameError, extract_roles, validate_username

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_oidc_client: OIDCClient | None = None


def _get_oidc_client() -> OIDCClient:
    global _oidc_client
    if _oidc_client is None:
        settings = get_settings()
        _oidc_client = OIDCClient(
            issuer=settings.oidc_issuer,
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            redirect_uri=settings.oidc_redirect_uri,
            leeway=settings.oidc_leeway,
        )
    return _oidc_client


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    url = await _get_oidc_client().authorization_url(request.session)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> RedirectResponse:
    settings = get_settings()
    try:
        claims = await _get_oidc_client().exchange_and_validate(
            code=code, state=state, session=request.session
        )
    except OIDCError as exc:
        _log.warning("oidc_callback_error", error=str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    raw_login = claims.get(settings.oidc_username_claim, "")
    try:
        login_name = validate_username(str(raw_login))
    except UsernameError as exc:
        _log.warning("oidc_invalid_username", username=raw_login)
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    roles = extract_roles(claims, settings.oidc_role_claim)
    sub = str(claims.get("sub", ""))

    await provision_user(login=login_name, sub=sub, data_root=_data_root())

    request.session["user"] = {"login": login_name, "roles": roles, "sub": sub}
    _log.info("user_logged_in", login=login_name, roles=roles)
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    login_name = request.session.get("user", {}).get("login", "?")
    request.session.clear()
    _log.info("user_logged_out", login=login_name)
    return RedirectResponse("/", status_code=302)


async def provision_user(login: str, sub: str, data_root: Path) -> None:
    """Crée le répertoire et config initiale si absent. Idempotent."""
    validate_username(login)
    user_dir = data_root / "users" / login
    config_path = user_dir / "config.yaml"

    if config_path.exists():
        _log.debug("user_already_provisioned", login=login)
        return

    ensure_user_dir(login)
    initial_config = {
        "version": "1",
        "secret_ns": str(uuid.uuid4()),
        "defaults": {},
        "harpocrate": {"api_key": ""},
        "git_credentials": [],
        "workspaces": [],
    }
    fd, tmp = tempfile.mkstemp(dir=user_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(initial_config, f, default_flow_style=False)
        os.replace(tmp, str(config_path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

    _log.info("user_provisioned", login=login, sub=sub)
