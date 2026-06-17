"""Tests de la couche persistance node_join_tokens (Tour 3)."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from portal.db.tables import node_join_tokens
from portal.db.tokens import _token_hash, consume_token, create_token

NODE = "worker-01"
ADDR = "10.0.0.1"


# ─── create_token ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_cleartext_token(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    assert len(token) > 20
    assert token != _token_hash(token)


@pytest.mark.asyncio
async def test_create_stores_hash_not_cleartext(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    row = (
        await db_conn.execute(
            node_join_tokens.select().where(
                node_join_tokens.c.token_hash == _token_hash(token)
            )
        )
    ).mappings().one()
    assert row["node_name"] == NODE
    assert row["address"] == ADDR
    assert row["used"] is False


# ─── consume_token ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_returns_node_name_and_address(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    node_name, address = await consume_token(token, db_conn)
    assert node_name == NODE
    assert address == ADDR


@pytest.mark.asyncio
async def test_consume_marks_as_used(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    await consume_token(token, db_conn)
    row = (
        await db_conn.execute(
            node_join_tokens.select().where(
                node_join_tokens.c.token_hash == _token_hash(token)
            )
        )
    ).mappings().one()
    assert row["used"] is True
    assert row["used_at"] is not None


@pytest.mark.asyncio
async def test_consume_unknown_token_raises(db_conn):
    with pytest.raises(ValueError, match="not found"):
        await consume_token(secrets.token_urlsafe(32), db_conn)


@pytest.mark.asyncio
async def test_consume_already_used_raises(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    await consume_token(token, db_conn)
    with pytest.raises(ValueError, match="already used"):
        await consume_token(token, db_conn)


@pytest.mark.asyncio
async def test_consume_expired_token_raises(db_conn):
    token = await create_token(NODE, ADDR, db_conn)
    # Forcer l'expiration directement en DB
    await db_conn.execute(
        update(node_join_tokens)
        .where(node_join_tokens.c.token_hash == _token_hash(token))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    with pytest.raises(ValueError, match="expired"):
        await consume_token(token, db_conn)
