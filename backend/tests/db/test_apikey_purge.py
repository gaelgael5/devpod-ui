"""Purge des clés API révoquées depuis plus de 24h (MCO)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, purge_revoked_apikeys, revoke_apikey
from portal.db.tables import mcp_apikey, users


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def _key(conn: AsyncConnection, key_id: str, owner: str = "alice") -> None:
    await insert_apikey(conn, id=key_id, owner_login=owner, token_hash="h" + key_id, label=key_id)


async def _ids(conn: AsyncConnection) -> set[str]:
    return {r[0] for r in (await conn.execute(select(mcp_apikey.c.id))).all()}


async def _set(conn: AsyncConnection, key_id: str, **values: object) -> None:
    await conn.execute(update(mcp_apikey).where(mcp_apikey.c.id == key_id).values(**values))


async def test_revoke_stamps_revoked_at(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _key(db_conn, "k1")
    assert await revoke_apikey(db_conn, "alice", "k1") is True
    row = (
        await db_conn.execute(
            select(mcp_apikey.c.revoked, mcp_apikey.c.revoked_at).where(mcp_apikey.c.id == "k1")
        )
    ).one()
    assert row[0] is True
    assert row[1] is not None


async def test_revoke_twice_keeps_initial_revoked_at(db_conn: AsyncConnection) -> None:
    # COALESCE : une seconde révocation ne réécrit pas l'instant initial.
    await _user(db_conn)
    await _key(db_conn, "k1")
    await revoke_apikey(db_conn, "alice", "k1")
    first = (
        await db_conn.execute(select(mcp_apikey.c.revoked_at).where(mcp_apikey.c.id == "k1"))
    ).scalar_one()
    await revoke_apikey(db_conn, "alice", "k1")
    second = (
        await db_conn.execute(select(mcp_apikey.c.revoked_at).where(mcp_apikey.c.id == "k1"))
    ).scalar_one()
    assert first == second


async def test_purge_removes_keys_revoked_over_24h_only(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _key(db_conn, "old")
    await _key(db_conn, "fresh")
    await revoke_apikey(db_conn, "alice", "old")
    await revoke_apikey(db_conn, "alice", "fresh")
    # 'old' révoquée il y a 25h ; 'fresh' à l'instant.
    await _set(db_conn, "old", revoked_at=datetime.now(UTC) - timedelta(hours=25))

    assert await purge_revoked_apikeys(db_conn) == 1
    assert await _ids(db_conn) == {"fresh"}


async def test_purge_never_touches_active_keys(db_conn: AsyncConnection) -> None:
    # Une clé jamais révoquée n'est jamais purgée, même très ancienne.
    await _user(db_conn)
    await _key(db_conn, "active")
    await _set(db_conn, "active", created_at=datetime.now(UTC) - timedelta(days=30))

    assert await purge_revoked_apikeys(db_conn, max_age_hours=0) == 0
    assert await _ids(db_conn) == {"active"}


async def test_purge_legacy_revoked_uses_created_at(db_conn: AsyncConnection) -> None:
    # Clé révoquée avant la colonne : revoked=true, revoked_at NULL → fallback created_at.
    await _user(db_conn)
    await _key(db_conn, "legacy")
    await _set(
        db_conn,
        "legacy",
        revoked=True,
        revoked_at=None,
        created_at=datetime.now(UTC) - timedelta(hours=25),
    )

    assert await purge_revoked_apikeys(db_conn) == 1
    assert await _ids(db_conn) == set()


async def test_purge_removes_grace_expired_keys(db_conn: AsyncConnection) -> None:
    """Les clés en grâce de rotation (expirées, jamais revoked) sont purgées après
    rétention — sinon elles s'accumuleraient indéfiniment."""
    await _user(db_conn)
    await _key(db_conn, "k-old-expired")
    await _key(db_conn, "k-fresh-expired")
    await _key(db_conn, "k-active")
    now = datetime.now(UTC)
    await _set(db_conn, "k-old-expired", expires_at=now - timedelta(hours=25))
    await _set(db_conn, "k-fresh-expired", expires_at=now - timedelta(minutes=10))

    n = await purge_revoked_apikeys(db_conn)

    assert n == 1
    ids = await _ids(db_conn)
    assert "k-old-expired" not in ids  # expirée depuis > 24h → purgée
    assert "k-fresh-expired" in ids  # expirée récemment → conservée (rétention)
    assert "k-active" in ids  # jamais touchée
