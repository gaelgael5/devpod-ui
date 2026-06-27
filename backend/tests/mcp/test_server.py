from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import METHOD_NOT_FOUND
from pydantic import AnyUrl
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, insert_backend_key, revoke_apikey, set_grant
from portal.db.mcp_audit import list_for_owner
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.aggregator import make_namespaced_uri
from portal.mcp.connections import BackendUnavailable
from portal.mcp.dispatch_common import extract_bearer, resolve_tenant
from portal.mcp.handlers import (
    GATEWAY_LIST_BACKENDS,
    build_prompt_descriptors,
    build_tool_descriptors,
    execute_prompt_get,
    execute_tool_call,
)
from portal.mcp.resources import build_resource_descriptors, execute_resource_read
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


async def test_gateway_list_backends_includes_health(db_conn: AsyncConnection) -> None:
    # TDD partiel DB-only : SKIP local (pas de Docker), rouge réel en CI Docker.
    import json

    from portal.mcp.monitor import BackendHealth, reset_health, set_health

    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)  # backend b1 ns=rag, grant ak1
    reset_health()
    set_health("b1", BackendHealth(status="up"))

    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name=GATEWAY_LIST_BACKENDS, arguments={},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    payload = json.loads(result.content[0].text)
    rag = next(b for b in payload if b["namespace"] == "rag")
    assert rag["health"] == "up"


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
    assert len(audit) == 1
    row = audit[0]
    assert row["status"] == "denied"
    assert row["backend_id"] is None
    assert row["latency_ms"] is None
    assert row["namespaced_name"] == "rag__ghost"


async def test_execute_tool_call_audits_timeout(db_conn: AsyncConnection) -> None:
    """BackendUnavailable → audit row status='timeout' est écrit avant le raise."""
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)

    @asynccontextmanager
    async def _unavailable(url: str, *, bearer: str | None = None, **kw: object):
        raise BackendUnavailable("down", backend_id="b1")
        yield  # rend la fonction un générateur asynccontextmanager valide

    with pytest.raises(McpError):
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__search", arguments={},
            open_session_fn=_unavailable,
        )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1
    row = audit[0]
    assert row["status"] == "timeout"
    assert row["backend_id"] == "b1"


async def test_execute_tool_call_audits_error_on_unresolvable_key(
    db_conn: AsyncConnection,
) -> None:
    """Clé harpocrate sans référence ${env://} → UnresolvableSecret → audit status='error'."""
    # runtime_secrets.py : storage_type='harpocrate' avec secret_value_vault_ref
    # qui NE commence PAS par '${env://}' → raise UnresolvableSecret.
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    await insert_backend_key(
        db_conn,
        id="k1",
        backend_id="b1",
        slug="prod",
        description="",
        storage_type="harpocrate",
        secret_value_local=None,
        secret_value_vault_ref="${vault://x}",  # non-env ref → UnresolvableSecret
        vault_identifier=None,
    )
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id="k1")

    with pytest.raises(McpError):
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__search", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    audit = await list_for_owner(db_conn, "alice")
    # Un seul enregistrement : celui de l'appel rag__search échoué
    error_rows = [r for r in audit if r["namespaced_name"] == "rag__search"]
    assert len(error_rows) == 1
    row = error_rows[0]
    assert row["status"] == "error"
    assert row["error"] == "key not resolvable"


# ---------------------------------------------------------------------------
# Task 5 (Plan 5) — prompts : build_prompt_descriptors + execute_prompt_get
# ---------------------------------------------------------------------------


async def _seed_backend_with_prompt(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )
    await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        conn, backend_id="b1", kind="prompt", original_name="welcome",
        definition={"name": "welcome", "description": "Prompt de bienvenue"},
        definition_hash="ph1",
    )


def _fake_backend_with_prompt() -> Server:
    srv: Server = Server("fake-backend-prompts")

    @srv.list_prompts()
    async def _lp() -> list[types.Prompt]:
        return [types.Prompt(name="welcome", description="Prompt de bienvenue")]

    @srv.get_prompt()
    async def _gp(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        who = (arguments or {}).get("who", "World")
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=f"Welcome {who}"),
                )
            ]
        )

    return srv


async def test_build_prompt_descriptors(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    prompts = await build_prompt_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    assert any(p.name == "rag__welcome" for p in prompts)


async def test_execute_prompt_get_routes(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    result = await execute_prompt_get(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__welcome", arguments={"who": "Bob"},
        open_session_fn=_patched_open_session(_fake_backend_with_prompt()),
    )
    assert "Bob" in result.messages[0].content.text
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "ok" and audit[0]["namespaced_name"] == "rag__welcome"


async def test_execute_prompt_get_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_prompt_get(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments=None,
            open_session_fn=_patched_open_session(_fake_backend_with_prompt()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "denied"


async def test_execute_prompt_get_audits_timeout(db_conn: AsyncConnection) -> None:
    """BackendUnavailable → audit row status='timeout', backend_id='b1'."""
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)

    @asynccontextmanager
    async def _unavailable(url: str, *, bearer: str | None = None, **kw: object):
        raise BackendUnavailable("down", backend_id="b1")
        yield  # rend la fonction un générateur asynccontextmanager valide

    with pytest.raises(McpError):
        await execute_prompt_get(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__welcome", arguments=None,
            open_session_fn=_unavailable,
        )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1
    row = audit[0]
    assert row["status"] == "timeout"
    assert row["backend_id"] == "b1"


async def test_execute_prompt_get_audits_error_on_unresolvable_key(
    db_conn: AsyncConnection,
) -> None:
    """Clé harpocrate sans référence ${env://} → UnresolvableSecret → audit status='error'."""
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    await insert_backend_key(
        db_conn,
        id="k1",
        backend_id="b1",
        slug="prod",
        description="",
        storage_type="harpocrate",
        secret_value_local=None,
        secret_value_vault_ref="${vault://x}",  # non-env ref → UnresolvableSecret
        vault_identifier=None,
    )
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id="k1")

    with pytest.raises(McpError):
        await execute_prompt_get(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__welcome", arguments=None,
            open_session_fn=_patched_open_session(_fake_backend_with_prompt()),
        )
    audit = await list_for_owner(db_conn, "alice")
    error_rows = [r for r in audit if r["namespaced_name"] == "rag__welcome"]
    assert len(error_rows) == 1
    row = error_rows[0]
    assert row["status"] == "error"
    assert row["error"] == "key not resolvable"


# ---------------------------------------------------------------------------
# Task 4 (Plan 5) — resources : build_resource_descriptors + execute_resource_read
# ---------------------------------------------------------------------------


async def _seed_backend_with_resource(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )
    await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        conn, backend_id="b1", kind="resource", original_name="resource://foo",
        definition={"uri": "resource://foo", "name": "Foo"},
        definition_hash="rh1",
    )


def _fake_backend_with_resource() -> Server:
    srv: Server = Server("fake-backend-resources")

    @srv.list_resources()
    async def _lr() -> list[types.Resource]:
        return [types.Resource(uri=AnyUrl("resource://foo"), name="Foo")]

    @srv.read_resource()
    async def _rr(uri: AnyUrl) -> list[ReadResourceContents]:
        return [ReadResourceContents(content="hello", mime_type="text/plain")]

    return srv


async def test_build_resource_descriptors_namespaces_uri(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)
    resources = await build_resource_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    uris = {str(r.uri) for r in resources}
    assert make_namespaced_uri("rag", "resource://foo") in uris


async def test_execute_resource_read_routes(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)
    namespaced = make_namespaced_uri("rag", "resource://foo")
    contents = await execute_resource_read(
        db_conn, apikey_id="ak1", owner_login="alice", namespaced_uri=namespaced,
        open_session_fn=_patched_open_session(_fake_backend_with_resource()),
    )
    assert contents[0].content == "hello"
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "ok" and audit[0]["namespaced_name"] == namespaced


async def test_execute_resource_read_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_resource_read(
            db_conn, apikey_id="ak1", owner_login="alice",
            namespaced_uri=make_namespaced_uri("rag", "resource://ghost"),
            open_session_fn=_patched_open_session(_fake_backend_with_resource()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND
    assert (await list_for_owner(db_conn, "alice"))[0]["status"] == "denied"
