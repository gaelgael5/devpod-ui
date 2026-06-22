from __future__ import annotations

import hashlib
import secrets as _secrets
import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from ..vault import session as vault_session
from ..vault.crypto import encrypt_token
from .models import ApikeyCreate, BackendCreate, GrantSet, KeyCreate

_log = structlog.get_logger(__name__)


class MCPError(Exception):
    pass


class NamespaceTaken(MCPError):
    pass


class NotFound(MCPError):
    pass


class InvalidReference(MCPError):
    pass


class VaultLocked(MCPError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


async def _require_owned_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> None:
    if await db.get_backend(conn, owner_login, backend_id) is None:
        raise NotFound(f"backend '{backend_id}' introuvable")


async def create_backend(conn: AsyncConnection, owner_login: str, body: BackendCreate) -> str:
    bid = new_id()
    try:
        await db.insert_backend(
            conn,
            id=bid,
            owner_login=owner_login,
            namespace=body.namespace,
            name=body.name,
            url=body.url,
            transport=body.transport,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"namespace '{body.namespace}' déjà utilisé") from exc
    _log.info("mcp_backend_created", login=owner_login, namespace=body.namespace)
    return bid


async def create_backend_key(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    session_id: str,
    body: KeyCreate,
) -> str:
    await _require_owned_backend(conn, owner_login, backend_id)

    local_blob: bytes | None = None
    vault_ref: str | None = None
    vault_id: str | None = None

    if body.storage_type == "local":
        master_key = vault_session.get_master_key(session_id)
        if master_key is None:
            raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
        local_blob = encrypt_token(body.secret_value, master_key)
    else:  # harpocrate : on ne stocke qu'une référence
        if not body.vault_identifier:
            raise InvalidReference("vault_identifier requis pour storage_type='harpocrate'")
        vault_id = body.vault_identifier
        vault_ref = f"${{vault://{body.vault_identifier}:mcp/{backend_id}/{body.slug}}}"

    kid = new_id()
    try:
        await db.insert_backend_key(
            conn,
            id=kid,
            backend_id=backend_id,
            slug=body.slug,
            description=body.description,
            storage_type=body.storage_type,
            secret_value_local=local_blob,
            secret_value_vault_ref=vault_ref,
            vault_identifier=vault_id,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"slug '{body.slug}' déjà utilisé pour ce backend") from exc
    _log.info("mcp_backend_key_created", login=owner_login, backend_id=backend_id, slug=body.slug)
    return kid


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

APIKEY_PREFIX = "mcpk_"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_apikey(
    conn: AsyncConnection, owner_login: str, body: ApikeyCreate
) -> tuple[str, str]:
    clear = APIKEY_PREFIX + _secrets.token_urlsafe(32)
    aid = new_id()
    await db.insert_apikey(
        conn, id=aid, owner_login=owner_login, token_hash=token_hash(clear), label=body.label
    )
    _log.info("mcp_apikey_created", login=owner_login, apikey_id=aid)
    return aid, clear


async def _require_owned_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> None:
    rows = await db.list_apikeys(conn, owner_login)
    if not any(r["id"] == apikey_id for r in rows):
        raise NotFound(f"apikey '{apikey_id}' introuvable")


async def set_grant(
    conn: AsyncConnection, owner_login: str, apikey_id: str, body: GrantSet
) -> None:
    await _require_owned_apikey(conn, owner_login, apikey_id)
    if await db.get_backend(conn, owner_login, body.backend_id) is None:
        raise NotFound(f"backend '{body.backend_id}' introuvable")
    # garde-fou : la clé doit exister ET appartenir au backend du grant
    if await db.get_backend_key(conn, body.backend_id, body.backend_key_id) is None:
        raise InvalidReference("backend_key_id n'appartient pas à ce backend")
    await db.set_grant(
        conn, apikey_id=apikey_id, backend_id=body.backend_id, backend_key_id=body.backend_key_id
    )
    _log.info("mcp_grant_set", login=owner_login, apikey_id=apikey_id, backend_id=body.backend_id)
