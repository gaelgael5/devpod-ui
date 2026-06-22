from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import (
    mcp_apikey,
    mcp_apikey_grant,
    mcp_audit_log,
    mcp_backend,
    mcp_tool_catalog,
    users,
)


async def _seed_backend(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_catalog_and_audit_smoke(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await db_conn.execute(
        insert(mcp_tool_catalog).values(
            backend_id="b1", kind="tool", original_name="search",
            definition={"name": "search"}, definition_hash="h",
        )
    )
    await db_conn.execute(
        insert(mcp_audit_log).values(status="ok", owner_login="alice", backend_id="b1")
    )
    rows = (await db_conn.execute(select(mcp_tool_catalog.c.original_name))).all()
    assert rows == [("search",)]


async def test_grant_curation_defaults(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await db_conn.execute(
        insert(mcp_apikey).values(
            id="a1", owner_login="alice", token_hash="tok_hash", label="cli"
        )
    )
    await db_conn.execute(
        insert(mcp_apikey_grant).values(apikey_id="a1", backend_id="b1")
    )
    row = (
        await db_conn.execute(
            select(mcp_apikey_grant.c.expose_mode, mcp_apikey_grant.c.expose)
            .where(mcp_apikey_grant.c.apikey_id == "a1")
        )
    ).one()
    assert row.expose_mode == "all"
    assert row.expose == []
