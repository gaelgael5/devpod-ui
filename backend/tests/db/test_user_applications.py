"""Tests de la persistance du kiosque d'applications (table user_applications)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from portal.db.tables import users
from portal.db.user_applications import (
    add_application,
    delete_application,
    list_applications,
)


async def _seed_user(conn, login: str) -> None:
    await conn.execute(
        users.insert().values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


@pytest.mark.asyncio
async def test_list_empty(db_conn):
    await _seed_user(db_conn, "alice")
    assert await list_applications("alice", db_conn) == []


@pytest.mark.asyncio
async def test_add_and_list_ordered(db_conn):
    await _seed_user(db_conn, "alice")
    a = await add_application("alice", "Doc", "https://doc.yoops.org", "📚", db_conn)
    b = await add_application("alice", "Rag", "https://rag.yoops.org", "", db_conn)
    assert a["position"] == 1
    assert b["position"] == 2
    apps = await list_applications("alice", db_conn)
    assert [x["name"] for x in apps] == ["Doc", "Rag"]
    assert apps[0]["icon"] == "📚"


@pytest.mark.asyncio
async def test_duplicate_name_raises(db_conn):
    await _seed_user(db_conn, "alice")
    await add_application("alice", "Doc", "https://doc.yoops.org", "", db_conn)
    with pytest.raises(IntegrityError):
        await add_application("alice", "Doc", "https://autre.io", "", db_conn)


@pytest.mark.asyncio
async def test_isolation_par_login(db_conn):
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    row = await add_application("alice", "Doc", "https://doc.yoops.org", "", db_conn)
    assert await list_applications("bob", db_conn) == []
    # bob ne peut pas supprimer la ligne d'alice
    assert await delete_application("bob", row["id"], db_conn) is False
    assert len(await list_applications("alice", db_conn)) == 1


@pytest.mark.asyncio
async def test_delete(db_conn):
    await _seed_user(db_conn, "alice")
    row = await add_application("alice", "Doc", "https://doc.yoops.org", "", db_conn)
    assert await delete_application("alice", row["id"], db_conn) is True
    assert await list_applications("alice", db_conn) == []
    assert await delete_application("alice", row["id"], db_conn) is False
