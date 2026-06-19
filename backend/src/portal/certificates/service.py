from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.certificates import (
    create_certificate,
    delete_certificate,
    get_certificate,
    get_private_key_local,
    list_certificates,
)
from ..vault import session as vault_session
from ..vault.crypto import decrypt_token, encrypt_token
from ..vault.keys import get_vault_client
from .keygen import CertType, generate_keypair

_log = structlog.get_logger(__name__)

_VAULT_PATH_PRIVATE = "certificats/{slug}/private"
_VAULT_PATH_PUBLIC = "certificats/{slug}/public"


class VaultLocked(Exception):
    pass


class CertAlreadyExists(Exception):
    pass


class CertNotFound(Exception):
    pass


def _require_master_key(session_id: str) -> bytes:
    mk = vault_session.get_master_key(session_id)
    if mk is None:
        raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
    return mk


async def register_certificate(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    cert_type: str,
    public_key: str,
    private_key_pem: str,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)

    if storage_type == "local":
        encrypted = encrypt_token(private_key_pem, master_key)
        vault_ref = None
        _write_harpocrate = None
    else:
        if vault_identifier is None:
            raise ValueError("vault_identifier requis pour storage_type != 'local'")
        encrypted = None
        vault_ref = f"${{vault://{vault_identifier}:certificats/{slug}/private}}"
        client = await get_vault_client(login, session_id, vault_identifier, conn)
        _write_harpocrate = (client, slug, public_key, private_key_pem)

    try:
        await create_certificate(
            login, slug, label, description, cert_type, public_key,
            private_key_local=encrypted,
            private_key_vault_ref=vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
            conn=conn,
        )
    except IntegrityError as exc:
        raise CertAlreadyExists(f"Un certificat '{slug}' existe déjà") from exc

    if _write_harpocrate is not None:
        client, slug_, pub, priv = _write_harpocrate
        await anyio.to_thread.run_sync(
            lambda: client.secrets.create(_VAULT_PATH_PUBLIC.format(slug=slug_), pub)
        )
        await anyio.to_thread.run_sync(
            lambda: client.secrets.create(_VAULT_PATH_PRIVATE.format(slug=slug_), priv)
        )
    _log.info("certificate_registered", login=login, slug=slug, storage_type=storage_type)


async def generate_and_register(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    cert_type: CertType,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> str:
    kp = await anyio.to_thread.run_sync(lambda: generate_keypair(cert_type))
    await register_certificate(
        login, session_id, slug, label, description, cert_type,
        kp.public_key, kp.private_key_pem,
        storage_type=storage_type,
        vault_identifier=vault_identifier,
        conn=conn,
    )
    return kp.public_key


async def list_user_certificates(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    return await list_certificates(login, conn)


async def reveal_private_key(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> str:
    master_key = _require_master_key(session_id)
    blob = await get_private_key_local(login, slug, conn)
    if blob is not None:
        return decrypt_token(blob, master_key)
    # Cas harpocrate : récupère via SDK
    row = await get_certificate(login, slug, conn)
    if row is None:
        raise CertNotFound(f"Certificat '{slug}' introuvable")
    if row["storage_type"] != "harpocrate" or row["owner_login"] != login:
        raise CertNotFound("Clé privée inaccessible")
    client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
    return await anyio.to_thread.run_sync(
        lambda: client.secrets.get(_VAULT_PATH_PRIVATE.format(slug=slug))
    )


async def remove_certificate(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> None:
    _require_master_key(session_id)
    row = await delete_certificate(login, slug, conn)
    if row is None:
        raise CertNotFound(f"Certificat '{slug}' introuvable ou non autorisé")
    if row["storage_type"] == "harpocrate" and row.get("vault_identifier"):
        client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
        def _make_delete(p: str) -> Callable[[], None]:
            def _delete() -> None:
                client.secrets.delete(p)

            return _delete

        for path in (
            _VAULT_PATH_PRIVATE.format(slug=slug),
            _VAULT_PATH_PUBLIC.format(slug=slug),
        ):
            try:
                await anyio.to_thread.run_sync(_make_delete(path))
            except Exception:
                _log.warning("cert_vault_delete_failed", slug=slug, path=path)
    _log.info("certificate_removed", login=login, slug=slug)
