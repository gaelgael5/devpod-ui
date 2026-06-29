from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_backend_key, mcp_profile, mcp_profile_entry

_PROFILE_COLS = [
    mcp_profile.c.id,
    mcp_profile.c.owner_login,
    mcp_profile.c.name,
    mcp_profile.c.description,
    mcp_profile.c.created_at,
    mcp_profile.c.updated_at,
]

_ENTRY_COLS = [
    mcp_profile_entry.c.profile_id,
    mcp_profile_entry.c.backend_id,
    mcp_profile_entry.c.backend_key_id,
    mcp_profile_entry.c.tools,
]


async def list_profiles(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_PROFILE_COLS)
        .where(mcp_profile.c.owner_login == owner_login)
        .order_by(mcp_profile.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_profile(
    conn: AsyncConnection, owner_login: str, profile_id: str
) -> dict[str, Any] | None:
    q = select(*_PROFILE_COLS).where(
        mcp_profile.c.id == profile_id,
        mcp_profile.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def insert_profile(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    name: str,
    description: str = "",
) -> None:
    await conn.execute(
        insert(mcp_profile).values(
            id=id,
            owner_login=owner_login,
            name=name,
            description=description,
        )
    )


async def update_profile(
    conn: AsyncConnection,
    owner_login: str,
    profile_id: str,
    *,
    name: str,
    description: str,
) -> bool:
    q = (
        update(mcp_profile)
        .where(
            mcp_profile.c.id == profile_id,
            mcp_profile.c.owner_login == owner_login,
        )
        .values(name=name, description=description, updated_at=func.now())
        .returning(mcp_profile.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_profile(
    conn: AsyncConnection, owner_login: str, profile_id: str
) -> bool:
    q = (
        delete(mcp_profile)
        .where(
            mcp_profile.c.id == profile_id,
            mcp_profile.c.owner_login == owner_login,
        )
        .returning(mcp_profile.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


async def list_profile_entries(
    conn: AsyncConnection, profile_id: str
) -> list[dict[str, Any]]:
    q = select(*_ENTRY_COLS).where(mcp_profile_entry.c.profile_id == profile_id)
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def upsert_profile_entry(
    conn: AsyncConnection,
    *,
    profile_id: str,
    backend_id: str,
    backend_key_id: str | None,
    tools: list[str] | None,
) -> None:
    stmt = pg_insert(mcp_profile_entry).values(
        profile_id=profile_id,
        backend_id=backend_id,
        backend_key_id=backend_key_id,
        tools=tools,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_mcp_profile_entry",
        set_={"backend_key_id": backend_key_id, "tools": tools},
    )
    await conn.execute(stmt)


async def delete_profile_entry(
    conn: AsyncConnection, profile_id: str, backend_id: str
) -> bool:
    q = (
        delete(mcp_profile_entry)
        .where(
            mcp_profile_entry.c.profile_id == profile_id,
            mcp_profile_entry.c.backend_id == backend_id,
        )
        .returning(mcp_profile_entry.c.profile_id)
    )
    return (await conn.execute(q)).first() is not None


async def list_entries_for_apikey(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[dict[str, Any]]:
    """Retourne les entries du profil associé à cette apikey (vide si pas de profil)."""
    from .tables import mcp_apikey

    subq = (
        select(mcp_apikey.c.profile_id)
        .where(
            mcp_apikey.c.id == apikey_id,
            mcp_apikey.c.owner_login == owner_login,
            mcp_apikey.c.profile_id.isnot(None),
        )
        .scalar_subquery()
    )
    q = select(*_ENTRY_COLS).where(mcp_profile_entry.c.profile_id == subq)
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def find_first_backend_key(
    conn: AsyncConnection, backend_id: str
) -> dict[str, Any] | None:
    """Première clé enabled pour ce backend — fallback si backend_key_id est null."""
    q = (
        select(
            mcp_backend_key.c.id,
            mcp_backend_key.c.storage_type,
            mcp_backend_key.c.secret_value_local,
            mcp_backend_key.c.secret_value_vault_ref,
        )
        .where(
            mcp_backend_key.c.backend_id == backend_id,
            mcp_backend_key.c.enabled.is_(True),
        )
        .order_by(mcp_backend_key.c.created_at)
        .limit(1)
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None
