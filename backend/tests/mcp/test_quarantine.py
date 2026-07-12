"""Quarantaine des primitives : helpers DB, résolution, erreur dédiée, logs de décision.

Complète test_catalog_resync.py : ici on couvre le chemin d'appel (resolve/handlers)
et la gestion de la quarantaine (liste, approbation, levée en masse).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from structlog.testing import capture_logs

from portal.db.mcp import insert_apikey
from portal.db.mcp_audit import list_for_owner
from portal.db.mcp_catalog import (
    clear_quarantine,
    list_quarantined,
    upsert_primitive,
)
from portal.db.mcp_profiles import insert_profile, upsert_profile_entry
from portal.db.tables import mcp_backend, users
from portal.mcp.aggregator import PrimitiveQuarantined, resolve_call
from portal.mcp.handlers import build_tool_descriptors, execute_tool_call


async def _seed(conn: AsyncConnection) -> None:
    """user alice + backend b1 (ns=rag) + profil p1 + apikey ak1 (tous tools)."""
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http", enabled=True,
        )
    )
    await insert_profile(conn, id="p1", owner_login="alice", name="Profil test")
    await insert_apikey(
        conn, id="ak1", owner_login="alice", token_hash="h", label="", profile_id="p1"
    )
    await upsert_profile_entry(
        conn, profile_id="p1", backend_id="b1", backend_key_id=None, tools=None
    )


async def _quarantine_search(conn: AsyncConnection) -> None:
    """Insère `search` puis le redéfinit → quarantaine collante."""
    await upsert_primitive(
        conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "description": "v1"}, definition_hash="h1",
    )
    await upsert_primitive(
        conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "description": "v2"}, definition_hash="h2",
    )


def _fake_backend() -> Server:
    srv: Server = Server("fake-backend")

    @srv.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _lt() -> list[types.Tool]:
        return [types.Tool(name="search", inputSchema={"type": "object"})]

    @srv.call_tool()  # type: ignore[untyped-decorator]
    async def _ct(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        return [types.TextContent(type="text", text="ok")]

    return srv


def _patched_open_session(server: Server) -> Any:
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw: Any) -> Any:
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _factory


# ---------------------------------------------------------------------------
# Helpers DB — list_quarantined / clear_quarantine / upsert protect=False
# ---------------------------------------------------------------------------


async def test_list_quarantined_returns_flagged_entries(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _quarantine_search(db_conn)

    rows = await list_quarantined(db_conn, "b1")
    assert len(rows) == 1
    assert rows[0]["kind"] == "tool" and rows[0]["original_name"] == "search"
    assert rows[0]["first_seen"] is not None and rows[0]["last_seen"] is not None


async def test_clear_quarantine_lifts_all_for_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _quarantine_search(db_conn)

    cleared = await clear_quarantine(db_conn, "b1")
    assert cleared == 1
    assert await list_quarantined(db_conn, "b1") == []
    # Idempotent
    assert await clear_quarantine(db_conn, "b1") == 0


async def test_upsert_protect_false_never_quarantines(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    flagged = await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search2"}, definition_hash="h2", protect=False,
    )
    assert flagged is False
    assert await list_quarantined(db_conn, "b1") == []


# ---------------------------------------------------------------------------
# Résolution — un tool quarantiné lève PrimitiveQuarantined (≠ inconnu)
# ---------------------------------------------------------------------------


async def test_resolve_call_quarantined_raises(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _quarantine_search(db_conn)

    with pytest.raises(PrimitiveQuarantined):
        await resolve_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            namespaced_name="rag__search", kind="tool",
        )


# ---------------------------------------------------------------------------
# Test imposé 8 + message dédié — décisions loggées à la réception
# ---------------------------------------------------------------------------


async def test_execute_tool_call_dispatched_is_logged(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )

    with capture_logs() as logs:
        result = await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__search", arguments={"q": "x"},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    assert result.isError is False

    received = [e for e in logs if e["event"] == "mcp_tool_call_received"]
    assert len(received) == 1
    assert received[0]["tool"] == "rag__search" and received[0]["apikey_id"] == "ak1"
    # Aucun argument d'appel dans les logs.
    assert "arguments" not in received[0] and "q" not in str(received[0])

    decisions = [e for e in logs if e["event"] == "mcp_tool_call_decision"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "dispatched"
    assert decisions[0]["backend_id"] == "b1"


async def test_execute_tool_call_unknown_logs_refusal(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)

    with capture_logs() as logs, pytest.raises(McpError) as exc:
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    assert exc.value.error.message == "unknown tool"

    decisions = [e for e in logs if e["event"] == "mcp_tool_call_decision"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "unknown_tool"
    assert decisions[0]["tool"] == "rag__ghost"


async def test_execute_tool_call_quarantined_message_and_audit(
    db_conn: AsyncConnection,
) -> None:
    await _seed(db_conn)
    await _quarantine_search(db_conn)

    with capture_logs() as logs, pytest.raises(McpError) as exc:
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__search", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    # Message dédié (spec 23 §13) — plus jamais le « unknown tool » trompeur.
    assert exc.value.error.message == "tool indisponible (en attente d'approbation)"

    decisions = [e for e in logs if e["event"] == "mcp_tool_call_decision"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "quarantined"
    assert decisions[0]["tool"] == "rag__search"

    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "denied"
    assert audit[0]["error"] == "quarantined"


# ---------------------------------------------------------------------------
# Instrumentation — tools/list servi au connecteur
# ---------------------------------------------------------------------------


async def test_build_tool_descriptors_logs_served_counts(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )

    with capture_logs() as logs:
        tools = await build_tool_descriptors(db_conn, apikey_id="ak1", owner_login="alice")

    served = [e for e in logs if e["event"] == "mcp_tools_list_served"]
    assert len(served) == 1
    assert served[0]["apikey_id"] == "ak1"
    assert served[0]["total"] == len(tools)
    assert served[0]["per_namespace"] == {"rag": 1}
