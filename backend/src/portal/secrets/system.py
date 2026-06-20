from __future__ import annotations

from typing import Literal

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import harpo_certificates, harpo_secrets, users
from portal.settings import get_settings
from portal.vault.crypto import decrypt_token, encrypt_token

_log = structlog.get_logger(__name__)

_SYSTEM_LOGIN = "__system__"
_SYSTEM_SECRET_NS = "00000000-0000-0000-0000-000000000001"


def _system_master_key() -> bytes:
    kek_hex = get_settings().portal_vault_kek
    if not kek_hex:
        raise RuntimeError(
            "PORTAL_VAULT_KEK non configuré — impossible de chiffrer les secrets système"
        )
    kek = bytes.fromhex(kek_hex)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"portal-system-vault")
    return hkdf.derive(kek)


async def ensure_system_user(conn: AsyncConnection) -> None:
    """Insère __system__ dans users si absent. Idempotent."""
    exists = (
        await conn.execute(select(users.c.login).where(users.c.login == _SYSTEM_LOGIN))
    ).one_or_none()
    if exists is None:
        await conn.execute(
            insert(users).values(
                login=_SYSTEM_LOGIN,
                version="1",
                secret_ns=_SYSTEM_SECRET_NS,
            )
        )
        _log.info("system_user_created")


async def store_system_secret(
    slug: str,
    label: str,
    value: str,
    storage_type: Literal["local", "harpocrate"],
    vault_identifier: str,
    conn: AsyncConnection,
) -> None:
    """Crée ou remplace une entrée harpo_secrets pour __system__."""
    await conn.execute(
        delete(harpo_secrets)
        .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_secrets.c.slug == slug)
    )
    if storage_type == "local":
        blob = encrypt_token(value, _system_master_key())
        await conn.execute(
            insert(harpo_secrets).values(
                slug=slug,
                label=label,
                description="",
                secret_type="CI_PASSWORD",
                secret_value_local=blob,
                secret_value_vault_ref=None,
                storage_type="local",
                vault_identifier="",
                owner_login=_SYSTEM_LOGIN,
                is_public=False,
            )
        )
    else:
        vault_ref = await _harpo_put_secret(slug, value, vault_identifier)
        await conn.execute(
            insert(harpo_secrets).values(
                slug=slug,
                label=label,
                description="",
                secret_type="CI_PASSWORD",
                secret_value_local=None,
                secret_value_vault_ref=vault_ref,
                storage_type="harpocrate",
                vault_identifier=vault_identifier,
                owner_login=_SYSTEM_LOGIN,
                is_public=False,
            )
        )
    _log.info("system_secret_stored", slug=slug, storage=storage_type)


async def reveal_system_secret(slug: str, conn: AsyncConnection) -> str:
    """Résout un secret système. Lève KeyError si absent."""
    row = (
        await conn.execute(
            select(harpo_secrets)
            .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
            .where(harpo_secrets.c.slug == slug)
        )
    ).mappings().one_or_none()
    if row is None:
        raise KeyError(f"System secret {slug!r} not found")
    if row["storage_type"] == "local":
        return decrypt_token(row["secret_value_local"], _system_master_key())
    return await _harpo_get_secret(slug, row["vault_identifier"])


async def delete_system_secret(slug: str, conn: AsyncConnection) -> None:
    """Supprime l'entrée harpo_secrets pour __system__ (no-op si absent)."""
    await conn.execute(
        delete(harpo_secrets)
        .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_secrets.c.slug == slug)
    )


async def store_system_cert(
    slug: str,
    label: str,
    private_pem: str,
    public_key: str,
    cert_type: str,
    storage_type: Literal["local", "harpocrate"],
    vault_identifier: str,
    conn: AsyncConnection,
) -> None:
    """Crée ou remplace une entrée harpo_certificates pour __system__."""
    await conn.execute(
        delete(harpo_certificates)
        .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_certificates.c.slug == slug)
    )
    if storage_type == "local":
        blob = encrypt_token(private_pem, _system_master_key())
        await conn.execute(
            insert(harpo_certificates).values(
                slug=slug,
                label=label,
                description="",
                cert_type=cert_type,
                public_key=public_key,
                private_key_local=blob,
                private_key_vault_ref=None,
                storage_type="local",
                vault_identifier="",
                owner_login=_SYSTEM_LOGIN,
                is_public=False,
            )
        )
    else:
        vault_ref = await _harpo_put_cert(slug, private_pem, vault_identifier)
        await conn.execute(
            insert(harpo_certificates).values(
                slug=slug,
                label=label,
                description="",
                cert_type=cert_type,
                public_key=public_key,
                private_key_local=None,
                private_key_vault_ref=vault_ref,
                storage_type="harpocrate",
                vault_identifier=vault_identifier,
                owner_login=_SYSTEM_LOGIN,
                is_public=False,
            )
        )
    _log.info("system_cert_stored", slug=slug, storage=storage_type)


async def reveal_system_cert(slug: str, conn: AsyncConnection) -> str:
    """Résout la clé privée PEM d'un cert système. Lève KeyError si absent."""
    row = (
        await conn.execute(
            select(harpo_certificates)
            .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
            .where(harpo_certificates.c.slug == slug)
        )
    ).mappings().one_or_none()
    if row is None:
        raise KeyError(f"System cert {slug!r} not found")
    if row["storage_type"] == "local":
        return decrypt_token(row["private_key_local"], _system_master_key())
    return await _harpo_get_cert(slug, row["vault_identifier"])


async def delete_system_cert(slug: str, conn: AsyncConnection) -> None:
    """Supprime l'entrée harpo_certificates pour __system__ (no-op si absent)."""
    await conn.execute(
        delete(harpo_certificates)
        .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_certificates.c.slug == slug)
    )


# ── Harpocrate helpers ────────────────────────────────────────────────────────


async def _harpo_put_secret(slug: str, value: str, vault_identifier: str) -> str:
    """Stocke un secret dans Harpocrate global; retourne la vault_ref."""
    import httpx

    from portal.db.global_config import get_cached_global

    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
            json={"value": value},
        )
        r.raise_for_status()
    return f"${{vault://{vault_identifier}:{hc.base_path}/{path}}}"


async def _harpo_get_secret(slug: str, vault_identifier: str) -> str:
    import httpx

    from portal.db.global_config import get_cached_global

    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
        )
        r.raise_for_status()
        return str(r.json()["value"])


async def _harpo_put_cert(slug: str, private_pem: str, vault_identifier: str) -> str:
    import httpx

    from portal.db.global_config import get_cached_global

    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}/private"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
            json={"value": private_pem},
        )
        r.raise_for_status()
    return f"${{vault://{vault_identifier}:{hc.base_path}/{path}}}"


async def _harpo_get_cert(slug: str, vault_identifier: str) -> str:
    import httpx

    from portal.db.global_config import get_cached_global

    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}/private"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
        )
        r.raise_for_status()
        return str(r.json()["value"])
