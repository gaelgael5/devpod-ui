"""Logique de l'Authorization Server OAuth (sans couche HTTP)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as mcp_db
from ..db import oauth as db
from ..mcp.service import APIKEY_PREFIX
from .pkce import verify_s256
from .tokens import new_client_id, new_secret, sha256_hex

_AUTHCODE_TTL = timedelta(minutes=5)
_REFRESH_PREFIX = "mcpr_"
_CODE_PREFIX = "mcpac_"


@dataclass
class OAuthError(Exception):
    """Erreur OAuth (RFC 6749) : `error` est le code normalisé."""

    error: str
    description: str = ""


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def ensure_valid_redirect_uri(uri: str) -> None:
    """Rejette tout redirect_uri non http(s) (anti-XSS : `javascript:`, `data:`…).

    https obligatoire ; http toléré uniquement en loopback (dev). Fragment interdit
    (RFC 6749 §3.1.2). La redirection finale fait `window.location.href = redirect`
    côté client : sans ce filtre, un `javascript:` exécuterait du code sur le portail.
    """
    p = urlparse(uri)
    loopback = p.hostname in _LOOPBACK_HOSTS
    if not (p.scheme == "https" or (p.scheme == "http" and loopback)):
        raise OAuthError("invalid_redirect_uri", "redirect_uri doit être https (ou http loopback)")
    if p.fragment:
        raise OAuthError("invalid_redirect_uri", "fragment interdit dans redirect_uri")


async def register_client(
    conn: AsyncConnection,
    *,
    redirect_uris: list[str],
    client_name: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enregistrement dynamique (DCR) d'un client public PKCE."""
    if not redirect_uris:
        raise OAuthError("invalid_redirect_uri", "redirect_uris requis")
    for uri in redirect_uris:
        ensure_valid_redirect_uri(uri)
    client_id = new_client_id()
    await db.insert_client(
        conn,
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=client_name,
        metadata=metadata or {},
    )
    return {
        "client_id": client_id,
        "redirect_uris": redirect_uris,
        "client_name": client_name,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


async def make_authcode(
    conn: AsyncConnection,
    *,
    client_id: str,
    owner_login: str,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    grants: list[dict[str, Any]],
) -> str:
    """Crée un code d'autorisation (TTL court) lié aux grants consentis ; retourne le code clair."""
    code = new_secret(_CODE_PREFIX)
    await db.insert_authcode(
        conn,
        code_hash=sha256_hex(code),
        client_id=client_id,
        owner_login=owner_login,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        scope=scope,
        grants=grants,
        expires_at=datetime.now(UTC) + _AUTHCODE_TTL,
    )
    return code


async def exchange_code(
    conn: AsyncConnection,
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Échange un code contre un couple access/refresh. Vérifie PKCE + client + redirect_uri."""
    row = await db.consume_authcode(conn, sha256_hex(code))
    if row is None:
        raise OAuthError("invalid_grant", "code invalide, expiré ou déjà utilisé")
    if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
        raise OAuthError("invalid_grant", "client_id/redirect_uri ne correspond pas au code")
    if not verify_s256(code_verifier, row["code_challenge"]):
        raise OAuthError("invalid_grant", "PKCE invalide")
    return await _issue(
        conn, owner_login=row["owner_login"], client_id=client_id, grants=row["grants"]
    )


async def refresh(
    conn: AsyncConnection, *, refresh_token: str, client_id: str
) -> dict[str, Any]:
    """Rotation : un nouveau couple access/refresh, l'ancien invalidé."""
    row = await db.find_apikey_by_refresh_hash(conn, sha256_hex(refresh_token))
    if row is None or row.get("client_id") != client_id:
        raise OAuthError("invalid_grant", "refresh token invalide")
    access = new_secret(APIKEY_PREFIX)
    new_refresh = new_secret(_REFRESH_PREFIX)
    await db.rotate_token(
        conn,
        apikey_id=row["id"],
        token_hash=sha256_hex(access),
        refresh_token_hash=sha256_hex(new_refresh),
    )
    return _token_response(access, new_refresh)


async def _issue(
    conn: AsyncConnection,
    *,
    owner_login: str,
    client_id: str,
    grants: list[dict[str, Any]],
) -> dict[str, Any]:
    access = new_secret(APIKEY_PREFIX)
    refresh_tok = new_secret(_REFRESH_PREFIX)
    apikey_id = uuid.uuid4().hex
    await db.insert_oauth_token(
        conn,
        id=apikey_id,
        owner_login=owner_login,
        token_hash=sha256_hex(access),
        client_id=client_id,
        refresh_token_hash=sha256_hex(refresh_tok),
        expires_at=None,  # long-lived révocable (D6)
    )
    for g in grants:
        await mcp_db.set_grant(
            conn,
            apikey_id=apikey_id,
            backend_id=g["backend_id"],
            backend_key_id=g.get("backend_key_id"),
            expose_mode=g.get("expose_mode", "all"),
            expose=g.get("expose", []),
            enabled=g.get("enabled", True),
            scopes=g.get("scopes"),
        )
    return _token_response(access, refresh_tok)


def _token_response(access: str, refresh_tok: str) -> dict[str, Any]:
    return {
        "access_token": access,
        "token_type": "Bearer",
        "refresh_token": refresh_tok,
        "expires_in": None,
    }
