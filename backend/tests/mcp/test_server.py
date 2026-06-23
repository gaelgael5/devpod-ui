from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import METHOD_NOT_FOUND
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, revoke_apikey, set_grant
from portal.db.mcp_audit import list_for_owner
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.server import (
    GATEWAY_LIST_BACKENDS,
    build_tool_descriptors,
    execute_tool_call,
    extract_bearer,
    resolve_tenant,
)
from portal.mcp.service import token_hash


def test_extract_bearer_parses_header() -> None:
    assert extract_bearer({"authorization": "Bearer mcpk_abc"}) == "mcpk_abc"
    assert extract_bearer({"authorization": "bearer mcpk_abc"}) == "mcpk_abc"
    assert extract_bearer({"authorization": "BEARER mcpk_abc"}) == "mcpk_abc"


def test_extract_bearer_missing_or_malformed() -> None:
    assert extract_bearer({}) is None
    assert extract_bearer({"authorization": ""}) is None
    assert extract_bearer({"authorization": "Basic xyz"}) is None
    assert extract_bearer({"authorization": "Bearer "}) is None


async def _seed_apikey(conn: AsyncConnection, token: str) -> str:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await insert_apikey(
        conn, id="ak1", owner_login="alice", token_hash=token_hash(token), label=""
    )
    return "ak1"


async def test_resolve_tenant_valid_token(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    tenant = await resolve_tenant(db_conn, "mcpk_secret")
    assert tenant is not None
    assert tenant["id"] == "ak1" and tenant["owner_login"] == "alice"


async def test_resolve_tenant_no_token_or_unknown(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    assert await resolve_tenant(db_conn, None) is None
    assert await resolve_tenant(db_conn, "mcpk_wrong") is None


async def test_resolve_tenant_revoked(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await revoke_apikey(db_conn, "alice", "ak1")
    assert await resolve_tenant(db_conn, "mcpk_secret") is None


async def _seed_backend_with_tool(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )
    await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "description": "Cherche", "inputSchema": {"type": "object"}},
        definition_hash="h1",
    )


async def test_build_tool_descriptors_namespaces_and_adds_native(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)

    tools = await build_tool_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    names = {t.name for t in tools}
    assert "rag__search" in names
    assert GATEWAY_LIST_BACKENDS in names
    rag = next(t for t in tools if t.name == "rag__search")
    assert rag.description == "Cherche"
    assert rag.inputSchema == {"type": "object"}


async def test_build_tool_descriptors_empty_still_has_native(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    tools = await build_tool_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    assert [t.name for t in tools] == [GATEWAY_LIST_BACKENDS]


# ---------------------------------------------------------------------------
# Task 3 — execute_tool_call
# ---------------------------------------------------------------------------


def _fake_backend() -> Server:
    srv: Server = Server("fake-backend")

    @srv.list_tools()
    async def _lt() -> list[types.Tool]:
        return [types.Tool(name="search", inputSchema={"type": "object"})]

    @srv.call_tool()
    async def _ct(name: str, arguments: dict) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"echo:{arguments.get('q', '')}")]

    return srv


def _patched_open_session(server: Server):
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _factory


async def test_execute_tool_call_routes_and_forwards(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)  # backend public (backend_key_id=None)

    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__search", arguments={"q": "hi"},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    assert result.isError is False
    assert result.content[0].text == "echo:hi"


async def test_execute_tool_call_unknown_raises_method_not_found(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND


async def test_execute_tool_call_native_gateway(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name=GATEWAY_LIST_BACKENDS, arguments={},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    assert result.isError is False
    assert "rag" in result.content[0].text


# ---------------------------------------------------------------------------
# Task 4 — audit exhaustif dans execute_tool_call
# ---------------------------------------------------------------------------


async def test_execute_tool_call_audits_ok(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__search", arguments={"q": "x"},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1
    row = audit[0]
    assert row["status"] == "ok"
    assert row["namespaced_name"] == "rag__search"
    assert row["backend_id"] == "b1"
    assert row["apikey_id"] == "ak1"
    assert row["latency_ms"] is not None


async def test_execute_tool_call_audits_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    with pytest.raises(McpError):
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1 and audit[0]["status"] == "denied"
