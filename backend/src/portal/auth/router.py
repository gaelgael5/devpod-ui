from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from pathlib import Path

import bcrypt as _bcrypt
import structlog
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from ..config.models import OidcConfig
from ..config.store import _data_root, ensure_user_dir, load_global
from ..settings import get_settings
from . import rbac as rbac_mod
from .oidc import OIDCClient, OIDCError
from .rbac import UsernameError, extract_roles, validate_username

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_oidc_client: OIDCClient | None = None
_oidc_client_key: tuple[str, str, str] | None = None


class LocalLoginRequest(BaseModel):
    username: str
    password: str


def auth_flags(oidc: OidcConfig, local_user: str, local_password_hash: str) -> dict[str, bool]:
    """Flags pour la page de login.

    OIDC (SSO) est piloté par la config (issuer + client_id renseignés via l'admin) ;
    le login local (admin break-glass) par le `.env` (LOCAL_USER/LOCAL_PASSWORD)
    ET par oidc.allow_local_auth (toggle UI).
    """
    oidc_configured = bool(oidc.issuer and oidc.client_id)
    # Le toggle allow_local_auth n'est respecté que si OIDC est opérationnel.
    # Sans OIDC : le compte break-glass reste toujours accessible (évite le lockout).
    local_allowed = oidc.allow_local_auth or not oidc_configured
    return {
        "oidc_enabled": oidc_configured,
        "local_auth_enabled": bool(local_user and local_password_hash and local_allowed),
    }


def _get_oidc_client() -> OIDCClient:
    """Client OIDC construit depuis la config (DB). Reconstruit si la config change."""
    global _oidc_client, _oidc_client_key
    settings = get_settings()
    oidc = load_global().auth.oidc
    key = (oidc.issuer, oidc.client_id, oidc.client_secret)
    if _oidc_client is None or _oidc_client_key != key:
        _oidc_client = OIDCClient(
            issuer=oidc.issuer,
            client_id=oidc.client_id,
            client_secret=oidc.client_secret,
            redirect_uri=settings.oidc_redirect_uri,
            leeway=settings.oidc_leeway,
        )
        _oidc_client_key = key
    return _oidc_client


@router.get("/config")
async def auth_config() -> dict[str, bool]:
    settings = get_settings()
    return auth_flags(
        load_global().auth.oidc, settings.local_user, settings.local_password_hash
    )


@router.post("/local-login")
async def local_login(request: Request, credentials: LocalLoginRequest) -> dict[str, bool]:
    settings = get_settings()
    oidc = load_global().auth.oidc
    oidc_configured = bool(oidc.issuer and oidc.client_id)
    local_allowed = oidc.allow_local_auth or not oidc_configured
    if not settings.local_user or not settings.local_password_hash or not local_allowed:
        raise HTTPException(status_code=404, detail="Local auth not configured")
    valid = credentials.username == settings.local_user and _bcrypt.checkpw(
        credentials.password.encode(),
        settings.local_password_hash.encode(),
    )
    if not valid:
        _log.warning("local_login_failed", username=credentials.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    await provision_user(login=settings.local_user, sub="local", data_root=_data_root())
    request.session.setdefault("session_id", str(uuid.uuid4()))
    request.session["user"] = {
        "login": settings.local_user,
        "roles": [load_global().auth.oidc.admin_role],
        "sub": "local",
    }
    _log.info("local_login_success", login=settings.local_user)
    return {"ok": True}


@router.get("/oidc")
async def oidc_login(request: Request) -> RedirectResponse:
    oidc = load_global().auth.oidc
    if not (oidc.issuer and oidc.client_id):
        # OIDC non configuré → retour à la page de login (jamais un 500).
        return RedirectResponse("/auth/login", status_code=302)
    url = await _get_oidc_client().authorization_url(request.session)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> RedirectResponse:
    oidc = load_global().auth.oidc
    try:
        claims = await _get_oidc_client().exchange_and_validate(
            code=code, state=state, session=request.session
        )
    except OIDCError as exc:
        _log.warning("oidc_callback_error", error=str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    raw_login = claims.get(oidc.username_claim, "")
    try:
        login_name = validate_username(str(raw_login))
    except UsernameError as exc:
        _log.warning("oidc_invalid_username", username=raw_login)
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    roles = extract_roles(claims, oidc.role_claim)
    sub = str(claims.get("sub", ""))

    await provision_user(login=login_name, sub=sub, data_root=_data_root())

    request.session.setdefault("session_id", str(uuid.uuid4()))
    request.session["user"] = {"login": login_name, "roles": roles, "sub": sub}
    _log.info("user_logged_in", login=login_name, roles=roles)
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    login_name = request.session.get("user", {}).get("login", "?")
    sid = request.session.get("session_id", "")
    if sid:
        from ..vault import session as vault_session

        vault_session.clear_session(sid)
    request.session.clear()
    _log.info("user_logged_out", login=login_name)
    resp = RedirectResponse("/", status_code=302)
    # Expire aussi un éventuel cookie de session legacy host-only (posé avant
    # COOKIE_DOMAIN) ; le SessionMiddleware, lui, ne supprime que celui sur son domaine.
    resp.delete_cookie("portal_session", path="/")
    return resp


async def provision_user(login: str, sub: str, data_root: Path) -> None:
    """Crée le répertoire + config YAML initiale si absent, upsert la row users. Idempotent."""
    validate_username(login)
    user_dir = data_root / "users" / login
    config_path = user_dir / "config.yaml"

    if config_path.exists():
        _log.debug("user_already_provisioned_yaml", login=login)
        with config_path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        secret_ns_str = str(raw.get("secret_ns", uuid.uuid4()))
    else:
        ensure_user_dir(login)
        secret_ns_str = str(uuid.uuid4())
        initial_config = {
            "version": "1",
            "secret_ns": secret_ns_str,
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

    # Upsert dans la table users (nécessaire pour les FK vault, workspaces, etc.)
    settings = get_settings()
    if settings.database_url:
        from sqlalchemy import insert, select

        from ..db.engine import _get_engine
        from ..db.tables import users

        async with _get_engine().begin() as conn:
            existing = (
                await conn.execute(select(users.c.login).where(users.c.login == login))
            ).scalar_one_or_none()
            if existing is None:
                await conn.execute(
                    insert(users).values(login=login, version="1", secret_ns=secret_ns_str)
                )
                _log.info("user_db_row_created", login=login)
                from ..mcp.devpod_bootstrap import ensure_devpod_backend

                await ensure_devpod_backend(conn, login)


@router.get("/caddy/verify")
async def caddy_verify(request: Request) -> Response:
    """Endpoint Caddy forward_auth — valide la session OIDC. §F-33 fail-closed.

    Caddy appelle cet endpoint pour chaque requête vers un workspace.
    Sans session valide → 302 vers le login du portail (URL absolue obligatoire —
    une URL relative causerait une boucle infinie car Caddy intercepterait la
    requête /auth/login sur le sous-domaine workspace et relancerait forward_auth).
    Session valide mais rôle insuffisant → 403. Sinon → 200.
    """
    settings = get_settings()
    external_url = load_global().server.external_url
    if not external_url:
        # external_url non configuré → fail-closed 403 plutôt que boucle infinie.
        # Une URL relative (/auth/login) resterait sur le sous-domaine workspace,
        # Caddy relancerait forward_auth, la même 302 serait émise → ERR_TOO_MANY_REDIRECTS.
        _log.error("caddy_verify_no_external_url", reason="portal_not_configured")
        return Response(
            status_code=403,
            content="Portal not configured — set external_url in admin settings",
        )
    login_url = f"{external_url}/auth/login"
    try:
        user = rbac_mod.get_current_user(request)
    except Exception as exc:
        _log.warning("caddy_verify_denied", reason="exception", exc_type=type(exc).__name__)
        return RedirectResponse(login_url, status_code=302)
    if user is None:
        _log.warning("caddy_verify_denied", reason="no_session")
        return RedirectResponse(login_url, status_code=302)
    allowed = {settings.oidc_user_role, settings.oidc_admin_role}
    if not set(user.roles) & allowed:
        _log.warning("caddy_verify_denied", reason="role_mismatch", login=user.login)
        return Response(status_code=403)
    return Response(status_code=200)


@router.get("/caddy/verify-workspace")
async def caddy_verify_workspace(request: Request) -> Response:
    """Forward_auth pour le proxy VS Code à sous-domaine fixe (vs_proxy_domain). §F-33.

    Vérifie la session OIDC puis résout le workspace actif de l'utilisateur.
    Retourne X-Workspace-Upstream: portal:{port} que Caddy injecte dans
    {http.vars.workspace_upstream} via le handler vars de handle_response.
    """
    from urllib.parse import parse_qs, urlparse

    from ..db.engine import _get_engine
    from ..db.workspace_status import list_by_login_db

    settings = get_settings()
    external_url = load_global().server.external_url
    if not external_url:
        _log.error("caddy_verify_workspace_no_external_url", reason="portal_not_configured")
        return Response(
            status_code=403,
            content="Portal not configured — set external_url in admin settings",
        )
    login_url = f"{external_url}/auth/login"
    try:
        user = rbac_mod.get_current_user(request)
    except Exception as exc:
        _log.warning(
            "caddy_verify_workspace_denied", reason="exception", exc_type=type(exc).__name__
        )
        return RedirectResponse(login_url, status_code=302)
    if user is None:
        _log.warning("caddy_verify_workspace_denied", reason="no_session")
        return RedirectResponse(login_url, status_code=302)
    allowed = {settings.oidc_user_role, settings.oidc_admin_role}
    if not set(user.roles) & allowed:
        _log.warning("caddy_verify_workspace_denied", reason="role_mismatch", login=user.login)
        return Response(status_code=403)

    # Extraire un ws_id éventuel depuis ?folder=/workspaces/{ws_id} dans l'URI forwarded.
    ws_id_hint: str | None = None
    forwarded_uri = request.headers.get("x-forwarded-uri", "")
    if forwarded_uri:
        parsed_uri = urlparse(forwarded_uri)
        folders = parse_qs(parsed_uri.query).get("folder", [])
        if folders:
            parts = folders[0].strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "workspaces":
                ws_id_hint = parts[1]

    async with _get_engine().begin() as conn:
        all_ws = await list_by_login_db(user.login, conn)

    running = [w for w in all_ws if w.get("status") == "running" and w.get("host_port")]
    if not running:
        _log.warning("caddy_verify_workspace_no_ws", login=user.login)
        return Response(status_code=503, content="No active workspace")

    # Préférer le workspace identifié par ?folder=, sinon le premier disponible.
    ws = next((w for w in running if w.get("ws_id") == ws_id_hint), running[0])
    host_port = ws["host_port"]
    _log.info(
        "caddy_verify_workspace_ok",
        login=user.login,
        ws_id=ws.get("ws_id"),
        host_port=host_port,
    )
    response = Response(status_code=200)
    response.headers["X-Workspace-Upstream"] = f"portal:{host_port}"
    return response
