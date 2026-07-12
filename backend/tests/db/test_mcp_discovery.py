"""Couche db des sources de découverte MCP (table mcp_discovery_source)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from portal.db import mcp_discovery as db
from portal.db.tables import users

pytestmark = pytest.mark.asyncio


async def _user(conn, login: str = "alice") -> str:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))
    return login


async def test_create_list_get_delete(db_conn) -> None:
    login = await _user(db_conn)
    created = await db.create_source(
        login, "Yoops", "yoops", "https://mcp.yoops.org", "k1", db_conn
    )
    assert created["slug"] == "yoops"
    sid = created["id"]

    listed = await db.list_sources(login, db_conn)
    assert [s["slug"] for s in listed] == ["yoops"]
    assert "secret_slug" in listed[0] and listed[0]["secret_slug"] == "k1"

    got = await db.get_source(login, sid, db_conn)
    assert got is not None and got["url"] == "https://mcp.yoops.org"

    assert await db.delete_source(login, sid, db_conn) is True
    assert await db.list_sources(login, db_conn) == []


async def test_unique_slug_per_user(db_conn) -> None:
    login = await _user(db_conn)
    await db.create_source(login, "A", "dup", "https://a", "", db_conn)
    with pytest.raises(IntegrityError):
        await db.create_source(login, "B", "dup", "https://b", "", db_conn)


async def test_isolated_per_user(db_conn) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await db.create_source("alice", "A", "s", "https://a", "", db_conn)
    await db.create_source("bob", "B", "s", "https://b", "", db_conn)  # même slug, autre user OK
    assert [s["label"] for s in await db.list_sources("alice", db_conn)] == ["A"]
    assert [s["label"] for s in await db.list_sources("bob", db_conn)] == ["B"]
