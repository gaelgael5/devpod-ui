from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
from .rbac import UsernameError, extract_roles, normalize_login, validate_username

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_oidc_client: OIDCClient | None = None
_oidc_client_key: tuple[str, str, str] | None = None

# Tâches fire-and-forget de fusion des comptes Termix au login (spec 18) : gardées le
# temps de leur exécution pour ne pas être ramassées par le GC.
_link_tasks: set[asyncio.Task[None]] = set()


def _fire_link_termix_accounts(login: str) -> None:
    """Lance (sans bloquer le login) la tentative de fusion interne↔OIDC des comptes
    Termix de `login`. Best-effort, silencieux si Termix indisponible."""
    from ..bastion.servers import try_link_accounts_for_user

    task = asyncio.create_task(try_link_accounts_for_user(login))
    _link_tasks.add(task)
    task.add_done_callback(_link_tasks.discard)


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
    # Login local = admin (rôle admin attribué en session ci-dessous) → persiste is_admin.
    await provision_user(
        login=settings.local_user, sub="local", data_root=_data_root(), is_admin=True
    )
    request.session.setdefault("session_id", str(uuid.uuid4()))
    # Horodatage de login absolu : borne l'âge maximal de la session indépendamment
    # du max_age glissant du cookie (bug 032).
    request.session["auth_time"] = int(time.time())
    request.session["user"] = {
        "login": settings.local_user,
        # Source de vérité unique du nom de rôle admin = settings (comme tout le
        # RBAC : rbac.py, sessions.py, compose.py, ssh_proxy.py, ownership.py).
        "roles": [settings.oidc_admin_role],
        "sub": "local",
    }
    # Pas de vrai jeton en login local : claims minimaux pour la page profil.
    request.session["token_claims"] = {"sub": "local", "preferred_username": settings.local_user}
    _log.info("local_login_success", login=settings.local_user)
    _fire_link_termix_accounts(settings.local_user)  # fusion comptes Termix (best-effort)
    from ..events.bus import emit_event

    await emit_event(
        "user.connected",
        actor=settings.local_user,
        subject={"login": settings.local_user, "sub": "local", "email": "", "identity": ""},
    )
    return {"ok": True}


# Claims OIDC exposés à l'utilisateur sur sa page profil (affichage + copie, ex.
# copier le `sub` pour le coller dans le champ Identité OBO ou d'autres apps).
_EXPOSED_CLAIMS = ("sub", "email", "preferred_username", "name", "iss", "aud", "exp", "iat")


def curate_token_claims(claims: Mapping[str, Any]) -> dict[str, str]:
    """Sous-ensemble sûr des claims OIDC à persister en session pour la page profil.

    On ne garde JAMAIS le jeton brut ni l'access_token (bearer) : uniquement des
    claims d'identité essentiels, courts, en chaînes (une liste comme `aud` est
    jointe). Destiné à l'affichage/copie, pas à une ré-authentification.
    """

    def _s(v: Any) -> str:
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v)
        return "" if v is None else str(v)

    return {k: _s(claims[k]) for k in _EXPOSED_CLAIMS if k in claims}


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

    raw_login = str(claims.get(oidc.username_claim, ""))
    login_name = normalize_login(raw_login)
    try:
        validate_username(login_name)
    except UsernameError as exc:
        _log.warning("oidc_invalid_username", username=raw_login, normalized=login_name)
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    roles = extract_roles(claims, oidc.role_claim)
    sub = str(claims.get("sub", ""))
    email = str(claims.get("email", ""))

    # Le sub OIDC est l'ancre d'identité. OIDC le garantit ; son absence est
    # anormale → fail closed (impossible d'ancrer de façon stable).
    if not sub:
        _log.warning("oidc_missing_sub", login=login_name)
        raise HTTPException(status_code=403, detail="OIDC token has no subject (sub)")

    # 1) Ancrage : un compte porte déjà ce sub → c'est l'identité canonique,
    #    quel que soit le preferred_username (qui a pu changer côté IdP).
    anchored = await resolve_login_by_sub(sub)
    if anchored is not None:
        if anchored != login_name:
            _log.info("oidc_login_matched_by_sub", derived=login_name, matched=anchored)
        login_name = anchored
    else:
        # 2) Sinon, rapprochement par email (1er login d'un compte pré-créé) ;
        #    3) sinon on garde le login dérivé du preferred_username.
        matched = await resolve_login_by_email(
            email, email_verified=claims.get("email_verified")
        )
        if matched is not None and matched != login_name:
            _log.info("oidc_login_matched_by_email", derived=login_name, matched=matched)
            login_name = matched

    is_admin = get_settings().oidc_admin_role in roles
    await provision_user(
        login=login_name, sub=sub, data_root=_data_root(), email=email, is_admin=is_admin
    )

    request.session.setdefault("session_id", str(uuid.uuid4()))
    # Horodatage de login absolu : borne l'âge maximal de la session indépendamment
    # du max_age glissant du cookie (bug 032).
    request.session["auth_time"] = int(time.time())
    request.session["user"] = {"login": login_name, "roles": roles, "sub": sub}
    # Claims essentiels curés (jamais le jeton brut) pour affichage/copie côté profil.
    request.session["token_claims"] = curate_token_claims(claims)
    _log.info("user_logged_in", login=login_name, roles=roles)
    _fire_link_termix_accounts(login_name)  # fusion comptes Termix (best-effort, spec 18)
    # Rafraîchissement d'identité à chaque login OIDC : re-synchronise l'aval
    # (ex. upsert du user dans Termix), idempotent. Best-effort (hors txn).
    from ..db.engine import _get_engine
    from ..db.user_config import get_user_actor
    from ..events.bus import emit_event

    async with _get_engine().connect() as conn:
        identity = await get_user_actor(login_name, conn) or ""
    subject = {"login": login_name, "sub": sub, "email": email, "identity": identity}
    await emit_event("user.refreshed", actor=login_name, subject=subject)
    # Ouverture d'une session de connexion (distinct du rafraîchissement d'identité).
    await emit_event("user.connected", actor=login_name, subject=subject)
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    session_user = request.session.get("user", {})
    login_name = session_user.get("login", "?")
    sub = session_user.get("sub", "")
    sid = request.session.get("session_id", "")
    if sid:
        from ..vault import session as vault_session

        vault_session.clear_session(sid)
    request.session.clear()
    _log.info("user_logged_out", login=login_name)
    # Fermeture de la session de connexion (best-effort, hors txn ; skip si anonyme).
    if login_name != "?":
        from ..events.bus import emit_event

        await emit_event(
            "user.disconnected",
            actor=login_name,
            subject={"login": login_name, "sub": sub},
        )
    resp = RedirectResponse("/", status_code=302)
    # Expire aussi un éventuel cookie de session legacy host-only (posé avant
    # COOKIE_DOMAIN) ; le SessionMiddleware, lui, ne supprime que celui sur son domaine.
    resp.delete_cookie("portal_session", path="/")
    return resp


async def resolve_login_by_sub(sub: str) -> str | None:
    """Login du compte ancré sur ce sujet OIDC, ou None si aucun (ni ancre en DB
    ni DB configurée). Ancre stable : insensible aux changements de
    preferred_username / email."""
    if not sub or not get_settings().database_url:
        return None
    from sqlalchemy import select

    from ..db.engine import _get_engine
    from ..db.tables import users

    async with _get_engine().connect() as conn:
        return (
            await conn.execute(select(users.c.login).where(users.c.sub == sub))
        ).scalar_one_or_none()


async def resolve_login_by_email(email: str, email_verified: object = None) -> str | None:
    """Rapproche un login OIDC d'un compte existant portant le même email.

    Un compte existant avec cet email = la même personne : on réutilise son login
    au lieu d'en dériver un nouveau du preferred_username (évite les doublons).
    Fail-closed sur les cas ambigus :
    - email absent, ou email_verified explicitement False (anti-usurpation) → None ;
    - plusieurs comptes partagent l'email → 403 (on ne choisit pas au hasard) ;
    - aucun match → None (flux de provisioning normal).
    """
    if not email or not get_settings().database_url:
        return None
    if email_verified is False:
        _log.warning("oidc_email_not_verified_skip_match", email=email)
        return None

    from sqlalchemy import select

    from ..db.engine import _get_engine
    from ..db.tables import users

    async with _get_engine().connect() as conn:
        logins = (
            (await conn.execute(select(users.c.login).where(users.c.email == email)))
            .scalars()
            .all()
        )
    if len(logins) > 1:
        _log.warning("oidc_email_ambiguous", email=email, logins=list(logins))
        raise HTTPException(
            status_code=403,
            detail="Multiple accounts share this email — contact an administrator",
        )
    return logins[0] if logins else None


async def provision_user(
    login: str, sub: str, data_root: Path, email: str = "", is_admin: bool = False
) -> None:
    """Crée le répertoire + config YAML initiale si absent, upsert la row users. Idempotent.

    `is_admin` (rôle OIDC) est persisté à CHAQUE login (création ET mise à jour) afin
    de pouvoir pousser aux admins hors contexte de requête (migration 101)."""
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
        from sqlalchemy import select, update
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from ..db.engine import _get_engine
        from ..db.tables import users

        async with _get_engine().begin() as conn:
            # INSERT atomique (même famille que bug 010) : deux callbacks de
            # login concurrents du même user ne doivent pas lever UniqueViolation.
            # DO NOTHING préserve la ligne existante (et son secret_ns).
            values = {
                "login": login,
                "version": "1",
                "secret_ns": secret_ns_str,
                "email": email,
                "is_admin": is_admin,
            }
            if sub:
                values["sub"] = sub
            result = await conn.execute(
                pg_insert(users)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[users.c.login])
            )
            if (result.rowcount or 0) > 0:
                _log.info("user_db_row_created", login=login)
                from ..mcp.devpod_bootstrap import ensure_devpod_backend

                await ensure_devpod_backend(conn, login)
                # Émis DANS la transaction de création (atomique avec la row users) :
                # déclencheur de provisioning aval (ex. créer le user dans Termix).
                from ..db.user_config import get_user_actor
                from ..events.bus import emit_event

                identity = await get_user_actor(login, conn) or ""
                await emit_event(
                    "user.created",
                    actor=login,
                    subject={"login": login, "sub": sub, "email": email, "identity": identity},
                    dedup_key=f"user:{login}",
                    conn=conn,
                )
            else:
                # Rôle admin re-synchronisé à chaque login (perte/gain de rôle reflétée).
                await conn.execute(
                    update(users).where(users.c.login == login).values(is_admin=is_admin)
                )
                if email:
                    await conn.execute(
                        update(users).where(users.c.login == login).values(email=email)
                    )
                # Ancrage de la ligne existante sur le sub : backfill si absent
                # (1er login OIDC d'un compte pré-existant), collision si un AUTRE
                # sub y est déjà lié (deux personnes, même login dérivé).
                if sub:
                    current = (
                        await conn.execute(
                            select(users.c.sub).where(users.c.login == login)
                        )
                    ).scalar_one()
                    if current is None:
                        await conn.execute(
                            update(users)
                            .where(users.c.login == login, users.c.sub.is_(None))
                            .values(sub=sub)
                        )
                        _log.info("user_sub_backfilled", login=login)
                    elif current != sub:
                        _log.warning(
                            "oidc_login_sub_collision", login=login, existing_sub=current
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="login already bound to another identity",
                        )


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
