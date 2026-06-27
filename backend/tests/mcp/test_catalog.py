from __future__ import annotations

import uuid
from typing import cast

from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ListToolsResult, ServerCapabilities, Tool
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_catalog import list_primitives, upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.catalog import sync_backend


def _server() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        return text

    return srv


class _ToolsOnlySession:
    """Session MCP minimale n'annonçant QUE la capability tools.

    FastMCP annonce toujours les trois familles ; il ne peut donc pas
    représenter un backend tools-only. Ce stub couvre exactement ce cas :
    capabilities → tools seul, et une énumération d'un outil.
    """

    def get_server_capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(tools={})

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="echo", inputSchema={"type": "object"})])


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


async def test_tools_only_does_not_prune_resources(db_conn: AsyncConnection) -> None:
    """Un sync tools-only ne doit PAS effacer les resources pré-existantes dans le catalogue."""
    await _seed(db_conn)

    # Pré-seed une resource pour b1
    await upsert_primitive(
        db_conn,
        backend_id="b1",
        kind="resource",
        original_name="demo://existing",
        definition={"uri": "demo://existing", "name": "Existing"},
        definition_hash="deadbeef",
    )

    # Sync avec un backend qui n'annonce QUE tools (resources/prompts non supportés)
    session = cast(ClientSession, _ToolsOnlySession())
    result = await sync_backend(db_conn, backend_id="b1", session=session)

    assert result["synced"] == 1  # un tool synced
    # La resource pré-existante DOIT survivre (kind resource non annoncé → non pruné)
    resources = await list_primitives(db_conn, "b1", "resource")
    assert len(resources) == 1 and resources[0]["original_name"] == "demo://existing"
    # Le tool est bien présent
    tools = await list_primitives(db_conn, "b1", "tool")
    assert len(tools) == 1 and tools[0]["original_name"] == "echo"
