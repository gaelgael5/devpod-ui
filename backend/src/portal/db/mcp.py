from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_apikey, mcp_apikey_grant, mcp_backend, mcp_backend_key

_BACKEND_COLS = [
    mcp_backend.c.id,
    mcp_backend.c.owner_login,
    mcp_backend.c.namespace,
    mcp_backend.c.name,
    mcp_backend.c.url,
    mcp_backend.c.transport,
    mcp_backend.c.enabled,
    mcp_backend.c.app_url,
    mcp_backend.c.created_at,
    mcp_backend.c.updated_at,
]


async def insert_backend(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    namespace: str,
    name: str,
    url: str,
    transport: str,
    app_url: str = "",
) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id=id,
            owner_login=owner_login,
            namespace=namespace,
            name=name,
            url=url,
            transport=transport,
            app_url=app_url,
        )
    )


async def list_all_enabled_backends(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les backends enabled (tous owners) — usage monitoring système."""
    rows = (
        await conn.execute(
            select(
                mcp_backend.c.id,
                mcp_backend.c.owner_login,
                mcp_backend.c.namespace,
                mcp_backend.c.name,
                mcp_backend.c.url,
                mcp_backend.c.transport,
                mcp_backend.c.enabled,
            ).where(mcp_backend.c.enabled.is_(True))
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_backends(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_BACKEND_COLS)
        .where(mcp_backend.c.owner_login == owner_login)
        .order_by(mcp_backend.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> dict[str, Any] | None:
    q = select(*_BACKEND_COLS).where(
        mcp_backend.c.id == backend_id,
        mcp_backend.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def update_backend(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    *,
    name: str,
    url: str,
    transport: str,
    enabled: bool,
    app_url: str = "",
) -> bool:
    q = (
        update(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .values(
            name=name, url=url, transport=transport, enabled=enabled,
            app_url=app_url, updated_at=func.now(),
        )
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_backend(conn: AsyncConnection, owner_login: str, backend_id: str) -> bool:
    q = (
        delete(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# Backend keys
# ---------------------------------------------------------------------------

_KEY_COLS = [
    mcp_backend_key.c.id,
    mcp_backend_key.c.backend_id,
    mcp_backend_key.c.slug,
    mcp_backend_key.c.description,
    mcp_backend_key.c.storage_type,
    mcp_backend_key.c.secret_value_vault_ref,
    mcp_backend_key.c.vault_identifier,
    mcp_backend_key.c.enabled,
    mcp_backend_key.c.created_at,
]


async def insert_backend_key(
    conn: AsyncConnection,
    *,
    id: str,
    backend_id: str,
    slug: str,
    description: str,
    storage_type: str,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    vault_identifier: str | None,
) -> None:
    await conn.execute(
        insert(mcp_backend_key).values(
            id=id,
            backend_id=backend_id,
            slug=slug,
            description=description,
            storage_type=storage_type,
            secret_value_local=secret_value_local,
            secret_value_vault_ref=secret_value_vault_ref,
            vault_identifier=vault_identifier,
        )
    )


async def list_backend_keys(conn: AsyncConnection, backend_id: str) -> list[dict[str, Any]]:
    q = (
        select(*_KEY_COLS)
        .where(mcp_backend_key.c.backend_id == backend_id)
        .order_by(mcp_backend_key.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend_key(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    q = select(*_KEY_COLS).where(
        mcp_backend_key.c.id == key_id,
        mcp_backend_key.c.backend_id == backend_id,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def get_backend_key_secret(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    """Récupère le secret chiffré d'une clé de service — usage RUNTIME uniquement.

    Contrairement à `get_backend_key`/`list_backend_keys`, sélectionne
    `secret_value_local` (blob chiffré KEK). Réservé à la résolution du secret
    sortant au runtime ; ne JAMAIS l'exposer dans un listing/registre.
    """
    row = (
        await conn.execute(
            select(
                mcp_backend_key.c.storage_type,
                mcp_backend_key.c.secret_value_local,
                mcp_backend_key.c.secret_value_vault_ref,
            ).where(
                mcp_backend_key.c.id == key_id,
                mcp_backend_key.c.backend_id == backend_id,
            )
        )
    ).mappings().first()
    return dict(row) if row else None


async def delete_backend_key(conn: AsyncConnection, backend_id: str, key_id: str) -> bool:
    q = (
        delete(mcp_backend_key)
        .where(mcp_backend_key.c.id == key_id, mcp_backend_key.c.backend_id == backend_id)
        .returning(mcp_backend_key.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

_APIKEY_COLS = [
    mcp_apikey.c.id,
    mcp_apikey.c.owner_login,
    mcp_apikey.c.label,
    mcp_apikey.c.kind,
    mcp_apikey.c.revoked,
    mcp_apikey.c.created_at,
]


async def insert_apikey(
    conn: AsyncConnection, *, id: str, owner_login: str, token_hash: str, label: str
) -> None:
    await conn.execute(
        insert(mcp_apikey).values(
            id=id, owner_login=owner_login, token_hash=token_hash, label=label
        )
    )


async def list_apikeys(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_APIKEY_COLS)
        .where(mcp_apikey.c.owner_login == owner_login)
        .order_by(mcp_apikey.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def find_apikey_by_hash(conn: AsyncConnection, token_hash: str) -> dict[str, Any] | None:
    q = select(*_APIKEY_COLS).where(
        mcp_apikey.c.token_hash == token_hash,
        mcp_apikey.c.revoked.is_(False),
        # Token OAuth expiré → introuvable (deny-by-default). NULL = pas d'expiration.
        or_(mcp_apikey.c.expires_at.is_(None), mcp_apikey.c.expires_at > func.now()),
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def get_apikey(
    conn: AsyncConnection, owner_login: str, apikey_id: str
) -> dict[str, Any] | None:
    q = select(*_APIKEY_COLS).where(
        mcp_apikey.c.id == apikey_id,
        mcp_apikey.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def revoke_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        update(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .values(revoked=True)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        delete(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------


async def set_grant(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    backend_id: str,
    backend_key_id: str | None,
    expose_mode: str = "all",
    expose: list[str] | None = None,
    enabled: bool = True,
    scopes: list[str] | None = None,
) -> None:
    expose = expose or []
    stmt = pg_insert(mcp_apikey_grant).values(
        apikey_id=apikey_id,
        backend_id=backend_id,
        backend_key_id=backend_key_id,
        expose_mode=expose_mode,
        expose=expose,
        enabled=enabled,
        scopes=scopes,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_mcp_apikey_grant_apikey_backend",
        set_={
            "backend_key_id": backend_key_id,
            "expose_mode": expose_mode,
            "expose": expose,
            "enabled": enabled,
            "scopes": scopes,
        },
    )
    await conn.execute(stmt)


async def list_grants(conn: AsyncConnection, apikey_id: str) -> list[dict[str, Any]]:
    q = select(
        mcp_apikey_grant.c.apikey_id,
        mcp_apikey_grant.c.backend_id,
        mcp_apikey_grant.c.backend_key_id,
        mcp_apikey_grant.c.expose_mode,
        mcp_apikey_grant.c.expose,
        mcp_apikey_grant.c.enabled,
        mcp_apikey_grant.c.scopes,
    ).where(mcp_apikey_grant.c.apikey_id == apikey_id)
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def delete_grant(conn: AsyncConnection, apikey_id: str, backend_id: str) -> bool:
    q = (
        delete(mcp_apikey_grant)
        .where(
            mcp_apikey_grant.c.apikey_id == apikey_id,
            mcp_apikey_grant.c.backend_id == backend_id,
        )
        .returning(mcp_apikey_grant.c.apikey_id)
    )
    return (await conn.execute(q)).first() is not None
