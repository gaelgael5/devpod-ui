from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, revoke_apikey, set_grant
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.server import (
    GATEWAY_LIST_BACKENDS,
    build_tool_descriptors,
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
