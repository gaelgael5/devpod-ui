from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

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
