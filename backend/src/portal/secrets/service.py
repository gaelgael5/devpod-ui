from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    get_secret_value_local,
    list_secrets,
    list_secrets_by_type,
    update_secret,
)
from ..vault import session as vault_session
from ..vault.crypto import decrypt_token, encrypt_token
from ..vault.keys import get_vault_client

_log = structlog.get_logger(__name__)

_VAULT_PATH = "secrets/{slug}/value"


class VaultLocked(Exception):
    pass


class SecretAlreadyExists(Exception):
    pass


class SecretNotFound(Exception):
    pass


def _require_master_key(session_id: str) -> bytes:
    mk = vault_session.get_master_key(session_id)
    if mk is None:
        raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
    return mk


def _make_harpo_write(client: Any, slug: str, value: str) -> Callable[[], None]:
    def _write() -> None:
        client.secrets.create(_VAULT_PATH.format(slug=slug), value)

    return _write


def _make_harpo_get(client: Any, slug: str) -> Callable[[], str]:
    def _get() -> str:
        return client.secrets.get(_VAULT_PATH.format(slug=slug))  # type: ignore[no-any-return]

    return _get


def _make_harpo_update(client: Any, slug: str, value: str) -> Callable[[], None]:
    def _update() -> None:
        client.secrets.put(_VAULT_PATH.format(slug=slug), value)

    return _update


def _make_harpo_delete(client: Any, slug: str) -> Callable[[], None]:
    def _delete() -> None:
        client.secrets.delete(_VAULT_PATH.format(slug=slug))

    return _delete


async def register_secret(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    secret_type: str,
    secret_value: str,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)

    if storage_type == "local":
        encrypted = encrypt_token(secret_value, master_key)
        vault_ref = None
        _harpo_write: tuple[Any, str, str] | None = None
    else:
        if vault_identifier is None:
            raise ValueError("vault_identifier requis pour storage_type != 'local'")
        encrypted = None
        vault_ref = f"${{vault://{vault_identifier}:{_VAULT_PATH.format(slug=slug)}}}"
        client = await get_vault_client(login, session_id, vault_identifier, conn)
        _harpo_write = (client, slug, secret_value)

    try:
        await create_secret(
            login,
            slug,
            label,
            description,
            secret_type,
            secret_value_local=encrypted,
            secret_value_vault_ref=vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
            conn=conn,
        )
    except IntegrityError as exc:
        raise SecretAlreadyExists(f"Un secret '{slug}' existe déjà") from exc

    if _harpo_write is not None:
        client_, slug_, val_ = _harpo_write
        await anyio.to_thread.run_sync(_make_harpo_write(client_, slug_, val_))

    _log.info("secret_registered", login=login, slug=slug, storage_type=storage_type)


async def list_user_secrets(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    return await list_secrets(login, conn)


async def list_user_secrets_by_type(
    login: str, secret_type: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    return await list_secrets_by_type(login, secret_type, conn)


async def reveal_secret(login: str, session_id: str, slug: str, conn: AsyncConnection) -> str:
    master_key = _require_master_key(session_id)

    blob = await get_secret_value_local(login, slug, conn)
    if blob is not None:
        return decrypt_token(blob, master_key)

    # Cas harpocrate : le secret n'est pas stocké localement
    row = await get_secret(login, slug, conn)
    if row is None or not row.get("is_own"):
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")

    client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
    return await anyio.to_thread.run_sync(_make_harpo_get(client, slug))


async def edit_secret(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    new_value: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)

    row = await get_secret(login, slug, conn)
    if row is None or not row.get("is_own"):
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")

    new_local: bytes | None = None
    new_vault_ref: str | None = None
    _harpo_update: tuple[Any, str, str] | None = None

    if new_value is not None:
        if row["storage_type"] == "local":
            new_local = encrypt_token(new_value, master_key)
        else:
            vault_identifier = row["vault_identifier"]
            client = await get_vault_client(login, session_id, vault_identifier, conn)
            _harpo_update = (client, slug, new_value)
            new_vault_ref = row.get("secret_value_vault_ref")

    updated = await update_secret(
        login,
        slug,
        label=label,
        description=description,
        secret_value_local=new_local,
        secret_value_vault_ref=new_vault_ref,
        conn=conn,
    )
    if not updated:
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")

    if _harpo_update is not None:
        client_, slug_, val_ = _harpo_update
        await anyio.to_thread.run_sync(_make_harpo_update(client_, slug_, val_))

    _log.info("secret_edited", login=login, slug=slug)


async def remove_secret(login: str, session_id: str, slug: str, conn: AsyncConnection) -> None:
    _require_master_key(session_id)

    row = await delete_secret(login, slug, conn)
    if row is None:
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")

    if row.get("storage_type") == "harpocrate" and row.get("vault_identifier"):
        client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
        try:
            await anyio.to_thread.run_sync(_make_harpo_delete(client, slug))
        except Exception:
            _log.warning("secret_vault_delete_failed", slug=slug)

    _log.info("secret_removed", login=login, slug=slug)
