"""Orchestration du flux OAuth client vers un backend amont (Tranche 2).

Colle ensemble le protocole (`mcp.oauth_client`), la persistance
(`db.mcp_oauth_client`) et le chiffrement KEK (`mcp.runtime_secrets`). C'est ici
que vivent l'horloge (calcul des expirations) et les règles de sécurité : liaison
`state`↔utilisateur (anti-CSRF), usage unique, isolation par propriétaire.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as mcp_db
from ..db import mcp_oauth_client as db
from ..oauth.pkce import generate_pkce
from . import oauth_client as oc
from .runtime_secrets import decrypt_service_key, encrypt_service_key

_log = structlog.get_logger(__name__)

_PENDING_TTL = timedelta(minutes=10)
_CLIENT_NAME = "devpod portal MCP gateway"
_CALLBACK_PATH = "/me/mcp/oauth/callback"


class OAuthFlowError(Exception):
    """Erreur applicative du flux (état invalide, backend non-OAuth, etc.)."""


def redirect_uri_for(external_url: str) -> str:
    return external_url.rstrip("/") + _CALLBACK_PATH


def _metadata_from_client(row: dict[str, Any]) -> oc.ASMetadata:
    return oc.ASMetadata(
        issuer=row["issuer"],
        authorization_endpoint=row["authorization_endpoint"],
        token_endpoint=row["token_endpoint"],
        registration_endpoint=row["registration_endpoint"],
    )


async def _ensure_client(
    conn: AsyncConnection, backend: dict[str, Any], redirect_uri: str
) -> dict[str, Any]:
    """Retourne le client OAuth du backend, l'enregistrant (DCR) au premier appel."""
    existing = await db.get_oauth_client(conn, backend["id"])
    if existing is not None:
        return existing

    metadata = await oc.discover_metadata(backend["url"], backend.get("oauth_auth_url") or None)
    scopes = " ".join(metadata.scopes_supported or [])
    client_id, client_secret = await oc.register_client(
        metadata, redirect_uri, client_name=_CLIENT_NAME, scopes=scopes
    )
    await db.upsert_oauth_client(
        conn,
        backend["id"],
        issuer=metadata.issuer,
        authorization_endpoint=metadata.authorization_endpoint,
        token_endpoint=metadata.token_endpoint,
        registration_endpoint=metadata.registration_endpoint,
        client_id=client_id,
        client_secret_enc=encrypt_service_key(client_secret) if client_secret else None,
        scopes=scopes,
    )
    _log.info("mcp_oauth_client_registered", backend_id=backend["id"], client_id=client_id)
    row = await db.get_oauth_client(conn, backend["id"])
    assert row is not None  # tout juste inséré dans la même transaction
    return row


async def start_authorization(
    conn: AsyncConnection, backend: dict[str, Any], user_login: str, external_url: str
) -> str:
    """Prépare une autorisation et retourne l'URL vers laquelle envoyer l'utilisateur."""
    if backend.get("auth_scheme") != "oauth":
        raise OAuthFlowError("le backend n'est pas en auth_scheme=oauth")

    redirect_uri = redirect_uri_for(external_url)
    client = await _ensure_client(conn, backend, redirect_uri)

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    await db.insert_pending(
        conn,
        state=state,
        backend_id=backend["id"],
        user_login=user_login,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(UTC) + _PENDING_TTL,
    )
    _log.info("mcp_oauth_authorize_started", backend_id=backend["id"], login=user_login)
    return oc.build_authorization_url(
        _metadata_from_client(client),
        client_id=client["client_id"],
        redirect_uri=redirect_uri,
        scopes=client["scopes"],
        state=state,
        code_challenge=challenge,
        resource=backend["url"],
    )


async def complete_authorization(
    conn: AsyncConnection, state: str, code: str, user_login: str
) -> str:
    """Consomme le `state`, échange le code, stocke le token. Retourne le backend_id."""
    pending = await db.consume_pending(conn, state)
    if pending is None:
        raise OAuthFlowError("state d'autorisation invalide ou expiré")
    if pending["user_login"] != user_login:
        # Liaison anti-CSRF : le state doit revenir sur la session qui l'a émis.
        raise OAuthFlowError("state ne correspond pas à l'utilisateur courant")

    backend_id: str = pending["backend_id"]
    backend = await mcp_db.get_backend(conn, user_login, backend_id)
    if backend is None:
        raise OAuthFlowError("backend introuvable")
    client = await db.get_oauth_client(conn, backend_id)
    if client is None:
        raise OAuthFlowError("client OAuth non enregistré pour ce backend")

    client_secret = (
        decrypt_service_key(client["client_secret_enc"]) if client["client_secret_enc"] else None
    )
    tok = await oc.exchange_code(
        _metadata_from_client(client),
        client_id=client["client_id"],
        client_secret=client_secret,
        code=code,
        code_verifier=pending["code_verifier"],
        redirect_uri=pending["redirect_uri"],
        resource=backend["url"],
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=tok.expires_in) if tok.expires_in else None
    await db.upsert_oauth_token(
        conn,
        backend_id,
        user_login,
        access_token_enc=encrypt_service_key(tok.access_token),
        refresh_token_enc=encrypt_service_key(tok.refresh_token) if tok.refresh_token else None,
        expires_at=expires_at,
        scopes=tok.scope or client["scopes"],
    )
    _log.info("mcp_oauth_token_stored", backend_id=backend_id, login=user_login)
    return backend_id


async def get_status(conn: AsyncConnection, backend_id: str, user_login: str) -> dict[str, Any]:
    """État de connexion OAuth de l'utilisateur pour ce backend (sans jamais le token)."""
    tok = await db.get_oauth_token(conn, backend_id, user_login)
    if tok is None:
        return {"connected": False, "expires_at": None, "scopes": ""}
    return {
        "connected": True,
        "expires_at": tok["expires_at"],
        "scopes": tok["scopes"],
    }


async def disconnect(conn: AsyncConnection, backend_id: str, user_login: str) -> bool:
    ok = await db.delete_oauth_token(conn, backend_id, user_login)
    if ok:
        _log.info("mcp_oauth_disconnected", backend_id=backend_id, login=user_login)
    return ok
