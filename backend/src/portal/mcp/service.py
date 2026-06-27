from __future__ import annotations

import hashlib
import secrets as _secrets
import uuid

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from ..vault import session as vault_session
from ..vault.keys import get_vault_client
from .models import ApikeyCreate, BackendCreate, GrantSet, KeyCreate
from .runtime_secrets import encrypt_service_key

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
            app_url=body.app_url,
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
        # Clé de service chiffrée avec la KEK système : la passerelle la
        # déchiffre en autonomie au runtime, sans session vault de l'owner.
        local_blob = encrypt_service_key(body.secret_value)
    else:  # harpocrate : écriture dans le coffre AVANT l'insert DB (pas de référence orpheline)
        if not body.vault_identifier:
            raise InvalidReference("vault_identifier requis pour storage_type='harpocrate'")
        if vault_session.get_master_key(session_id) is None:
            raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
        vault_id = body.vault_identifier
        harpo_path = f"mcp/{backend_id}/{body.slug}/value"
        vault_ref = f"${{vault://{body.vault_identifier}:{harpo_path}}}"
        harpo_client = await get_vault_client(owner_login, session_id, body.vault_identifier, conn)
        await anyio.to_thread.run_sync(
            lambda: harpo_client.secrets.create(harpo_path, body.secret_value)
        )

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
    if await db.get_apikey(conn, owner_login, apikey_id) is None:
        raise NotFound(f"apikey '{apikey_id}' introuvable")


async def set_grant(
    conn: AsyncConnection, owner_login: str, apikey_id: str, body: GrantSet
) -> None:
    await _require_owned_apikey(conn, owner_login, apikey_id)
    if await db.get_backend(conn, owner_login, body.backend_id) is None:
        raise NotFound(f"backend '{body.backend_id}' introuvable")
    # backend_key_id None = backend public (sans auth) : aucune clé à valider.
    # Sinon, garde-fou : la clé doit exister ET appartenir au backend du grant.
    if (
        body.backend_key_id is not None
        and await db.get_backend_key(conn, body.backend_id, body.backend_key_id) is None
    ):
        raise InvalidReference("backend_key_id n'appartient pas à ce backend")
    await db.set_grant(
        conn,
        apikey_id=apikey_id,
        backend_id=body.backend_id,
        backend_key_id=body.backend_key_id,
        expose_mode=body.expose_mode,
        expose=body.expose,
        enabled=body.enabled,
        scopes=[str(s) for s in body.scopes] if body.scopes is not None else None,
    )
    _log.info("mcp_grant_set", login=owner_login, apikey_id=apikey_id, backend_id=body.backend_id)
