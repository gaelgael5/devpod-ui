from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_catalog import list_primitives
from portal.db.tables import mcp_backend, users
from portal.mcp.catalog import sync_backend


def _server() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        return text

    return srv


async def _seed(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_sync_backend_populates_catalog(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    # create_connected_server_and_client_session calls initialize() internally —
    # no explicit initialize() needed here.
    async with create_connected_server_and_client_session(_server()) as session:
        result = await sync_backend(db_conn, backend_id="b1", session=session)

    assert result["synced"] == 1
    assert result["quarantined"] == []
    tools = await list_primitives(db_conn, "b1", "tool")
    assert len(tools) == 1 and tools[0]["original_name"] == "echo"
