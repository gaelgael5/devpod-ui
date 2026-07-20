from __future__ import annotations

import time
from collections.abc import Mapping

from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    ErrorData,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import find_apikey_by_hash, get_backend_key_secret
from portal.db.mcp_audit import record as audit_record
from portal.db.user_config import get_user_sub
from portal.mcp.aggregator import CallTarget
from portal.mcp.obo import build_obo_headers
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key
from portal.mcp.service import token_hash

_BEARER_PREFIX = "bearer "

_UNAUTHORIZED = ErrorData(code=INVALID_PARAMS, message="missing or invalid API key")


async def obo_headers_for(
    conn: AsyncConnection, target: CallTarget, owner_login: str, bearer: str | None
) -> dict[str, str] | None:
    """En-têtes on-behalf-of signés si le backend l'a activé et qu'une clé existe.

    L'acteur propagé est le **sub OIDC** (`users.sub`), ancre d'identité stable —
    pas le login (mutable). Le secret de signature est la clé sortante (`bearer`) :
    seul le portail la détient, donc un client ne peut pas forger l'identité.
    Rien propagé si : backend non opt-in, pas de clé, ou utilisateur sans sub."""
    if not (target.forward_identity and bearer):
        return None
    sub = await get_user_sub(owner_login, conn)
    if not sub:
        return None
    return build_obo_headers(sub, bearer, now=int(time.time()))


def extract_bearer(headers: Mapping[str, str]) -> str | None:
    """Extrait le token Bearer de l'en-tête Authorization (schéma insensible à la casse)."""
    raw = headers.get("authorization")
    if not raw or not raw.lower().startswith(_BEARER_PREFIX):
        return None
    token = raw[len(_BEARER_PREFIX) :].strip()
    return token or None


async def resolve_tenant(conn: AsyncConnection, token: str | None) -> dict[str, object] | None:
    """Résout le token apikey clair en ligne apikey (non révoquée) ou None."""
    if not token:
        return None
    return await find_apikey_by_hash(conn, token_hash(token))


async def resolve_bearer(
    conn: AsyncConnection,
    target: CallTarget,
    *,
    name: str,
    apikey_id: str,
    owner_login: str,
) -> str | None:
    """Résout la clé sortante en bearer HTTP (None si pas de clé).

    Audit 'error' + McpError(INTERNAL_ERROR) si non résolvable.
    """
    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id
        else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        await audit_record(
            conn,
            apikey_id=apikey_id,
            owner_login=owner_login,
            namespaced_name=name,
            backend_id=target.backend_id,
            backend_key_id=target.backend_key_id,
            latency_ms=None,
            status="error",
            error="key not resolvable",
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message="outbound key not resolvable at runtime")
        ) from exc
    return secret.reveal() if secret else None
