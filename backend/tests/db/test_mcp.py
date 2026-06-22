from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import (
    delete_backend,
    get_backend,
    insert_backend,
    list_backends,
    update_backend,
)
from portal.db.tables import (
    mcp_apikey,
    mcp_apikey_grant,
    mcp_backend,
    mcp_backend_key,
    users,
)

pytestmark = pytest.mark.asyncio


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(
        insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


async def test_tables_smoke(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await db_conn.execute(
        insert(mcp_backend).values(
            id="b1",
            owner_login="alice",
            namespace="rag",
            name="RAG",
            url="https://rag.yoops.org/mcp",
            transport="streamable_http",
        )
    )
    await db_conn.execute(
        insert(mcp_backend_key).values(
            id="k1",
            backend_id="b1",
            slug="read",
            description="lecture seule",
            storage_type="local",
            secret_value_local=b"\x00" * 16,
        )
    )
    await db_conn.execute(
        insert(mcp_apikey).values(id="a1", owner_login="alice", token_hash="h", label="cli")
    )
    await db_conn.execute(
        insert(mcp_apikey_grant).values(apikey_id="a1", backend_id="b1", backend_key_id="k1")
    )
    rows = (await db_conn.execute(select(mcp_backend.c.namespace))).all()
    assert rows == [("rag",)]


async def test_backend_crud(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    rows = await list_backends(db_conn, "alice")
    assert len(rows) == 1 and rows[0]["namespace"] == "rag"
    assert "owner_login" in rows[0]

    got = await get_backend(db_conn, "alice", "b1")
    assert got is not None and got["name"] == "RAG"

    # isolation : bob ne voit rien
    await _user(db_conn, "bob")
    assert await get_backend(db_conn, "bob", "b1") is None
    assert await list_backends(db_conn, "bob") == []

    ok = await update_backend(
        db_conn, "alice", "b1", name="RAG2", url="https://rag2/mcp",
        transport="sse", enabled=False,
    )
    assert ok is True
    got = await get_backend(db_conn, "alice", "b1")
    assert got["name"] == "RAG2" and got["enabled"] is False

    assert await delete_backend(db_conn, "alice", "b1") is True
    assert await get_backend(db_conn, "alice", "b1") is None
