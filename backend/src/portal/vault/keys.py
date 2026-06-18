from __future__ import annotations

from typing import Any

import anyio
import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.vault_keys import (
    create_vault_key,
    delete_vault_key,
    get_encrypted_token,
    list_vault_keys,
    vault_key_exists,
)
from . import session as vault_session
from .crypto import decrypt_token, encrypt_token

_log = structlog.get_logger(__name__)


class VaultLocked(Exception):
    pass


class KeyAlreadyExists(Exception):
    pass


class KeyNotFound(Exception):
    pass


def _require_master_key(session_id: str) -> bytes:
    mk = vault_session.get_master_key(session_id)
    if mk is None:
        raise VaultLocked("Vault locked — unlock with your PIN first")
    return mk


async def add_key(
    login: str,
    session_id: str,
    identifier: str,
    token: str,
    url: str,
    description: str,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)
    if await vault_key_exists(login, identifier, conn):
        raise KeyAlreadyExists(f"Key {identifier!r} already exists")
    encrypted = encrypt_token(token, master_key)
    await create_vault_key(login, identifier, encrypted, url, description, conn)
    _log.info("vault_key_added", login=login, identifier=identifier)


async def list_keys(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    return await list_vault_keys(login, conn)


async def delete_key(
    login: str, session_id: str, identifier: str, conn: AsyncConnection
) -> None:
    _require_master_key(session_id)
    if not await delete_vault_key(login, identifier, conn):
        raise KeyNotFound(f"Key {identifier!r} not found")
    _log.info("vault_key_deleted", login=login, identifier=identifier)


async def get_vault_client(
    login: str, session_id: str, identifier: str, conn: AsyncConnection
) -> Any:
    from harpocrate import VaultClient  # type: ignore[import-untyped]

    master_key = _require_master_key(session_id)
    encrypted = await get_encrypted_token(login, identifier, conn)
    if encrypted is None:
        raise KeyNotFound(f"Key {identifier!r} not found")
    token = decrypt_token(encrypted, master_key)
    keys = await list_vault_keys(login, conn)
    url = next(
        (r["url"] for r in keys if r["identifier"] == identifier),
        "https://vault.yoops.org",
    )
    return VaultClient(token=token, base_url=url)


async def test_key_connection(
    login: str, session_id: str, identifier: str, conn: AsyncConnection
) -> dict[str, Any]:
    client = await get_vault_client(login, session_id, identifier, conn)
    info = await anyio.to_thread.run_sync(client.whoami)
    return {
        "api_key_id": str(info.api_key_id),
        "wallet_id": str(info.wallet_id),
        "permissions": info.permissions,
    }
