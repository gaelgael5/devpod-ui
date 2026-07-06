"""Tests de convergence du resync du catalogue fédéré (bug create_document).

Couvre la liste imposée : nominal/idempotent, ajout, retrait, down→up,
down conserve le registre, changement partiel, rollback mi-parcours,
concurrence — plus le flag `quarantine_disabled` par backend et le log
de resync à delta nominatif.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from mcp import ClientSession
from mcp.types import ListToolsResult, ServerCapabilities, Tool
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from structlog.testing import capture_logs

from portal.db.mcp_catalog import list_primitives
from portal.db.tables import mcp_backend, users
from portal.mcp.catalog import fetch_backend_catalog, sync_backend, write_backend_catalog
from portal.mcp.connections import BackendUnavailable
from portal.mcp.monitor import monitor_backend_once, reset_health


class _StubSession:
    """Session MCP tools-only dont la liste d'outils est pilotée par le test."""

    def __init__(self, tools: dict[str, str]) -> None:
        self._tools = tools

    def get_server_capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(tools={})

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name=name, description=desc, inputSchema={"type": "object"})
                for name, desc in self._tools.items()
            ]
        )


def _session(tools: dict[str, str]) -> ClientSession:
    return cast(ClientSession, _StubSession(tools))


def _session_fn(tools: dict[str, str]) -> Any:
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw: Any) -> Any:
        yield _session(tools)

    return _factory


@asynccontextmanager
async def _unavailable_session(url: str, *, bearer: str | None = None, **kw: Any) -> Any:
    raise BackendUnavailable("connexion refusée", backend_id="b1")
    yield  # noqa: RET504  # unreachable — fait du factory un générateur


async def _seed(conn: AsyncConnection, *, quarantine_disabled: bool = False) -> dict[str, Any]:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    row: dict[str, Any] = {
        "id": "b1", "owner_login": "alice", "namespace": "rag", "name": "RAG",
        "url": "https://rag/mcp", "transport": "streamable_http", "enabled": True,
        "quarantine_disabled": quarantine_disabled,
    }
    await conn.execute(insert(mcp_backend).values(**row))
    return row


async def _tool_names(conn: AsyncConnection, backend_id: str = "b1") -> set[str]:
    return {p["original_name"] for p in await list_primitives(conn, backend_id, "tool")}


async def _resync(conn: AsyncConnection, tools: dict[str, str], **kw: Any) -> dict[str, Any]:
    return await sync_backend(conn, backend_id="b1", session=_session(tools), **kw)


# ---------------------------------------------------------------------------
# Test imposé 1 — nominal + idempotence
# ---------------------------------------------------------------------------


async def test_resync_nominal_idempotent(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    tools = {"a": "A", "b": "B", "c": "C"}

    result = await _resync(db_conn, tools)
    assert result["synced"] == 3
    assert await _tool_names(db_conn) == {"a", "b", "c"}

    # Rejoué à l'identique : même état, aucune quarantaine, aucun doublon.
    result = await _resync(db_conn, tools)
    assert result["synced"] == 3
    assert result["quarantined"] == []
    assert await _tool_names(db_conn) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Test imposé 2 — ajout sans perte
# ---------------------------------------------------------------------------


async def test_resync_addition_preserves_existing(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _resync(db_conn, {"a": "A", "b": "B"})

    await _resync(db_conn, {"a": "A", "b": "B", "c": "C"})
    assert await _tool_names(db_conn) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Test imposé 3 — retrait ciblé
# ---------------------------------------------------------------------------


async def test_resync_removal_keeps_others(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _resync(db_conn, {"a": "A", "b": "B", "c": "C"})

    await _resync(db_conn, {"a": "A", "c": "C"})
    assert await _tool_names(db_conn) == {"a", "c"}


# ---------------------------------------------------------------------------
# Test imposé 4 — séquence down→up : rien de perdu (scénario du bug)
# ---------------------------------------------------------------------------


async def test_down_then_up_restores_full_registry(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed(db_conn)
    tools = {"a": "A", "b": "B", "c": "C"}
    await _resync(db_conn, tools)

    # Backend down pendant le redéploiement : un resync a lieu et échoue.
    health = await monitor_backend_once(db_conn, backend, open_session_fn=_unavailable_session)
    assert health.status == "down"
    assert await _tool_names(db_conn) == {"a", "b", "c"}

    # Retour up avec la même liste : registre intégral, aucune quarantaine.
    health = await monitor_backend_once(db_conn, backend, open_session_fn=_session_fn(tools))
    assert health.status == "up"
    assert await _tool_names(db_conn) == {"a", "b", "c"}
    prims = await list_primitives(db_conn, "b1", "tool")
    assert all(not p["quarantined"] for p in prims)


# ---------------------------------------------------------------------------
# Test imposé 5 — backend down au resync : registre conservé intact
# ---------------------------------------------------------------------------


async def test_backend_down_preserves_registry(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed(db_conn)
    await _resync(db_conn, {"a": "A", "b": "B"})

    health = await monitor_backend_once(db_conn, backend, open_session_fn=_unavailable_session)
    assert health.status == "down"
    assert await _tool_names(db_conn) == {"a", "b"}


# ---------------------------------------------------------------------------
# Test imposé 6 — retrait + ajout simultanés : état final exact
# ---------------------------------------------------------------------------


async def test_partial_change_exact_final_state(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _resync(db_conn, {"a": "A", "b": "B", "c": "C"})

    await _resync(db_conn, {"b": "B", "c": "C", "d": "D"})
    assert await _tool_names(db_conn) == {"b", "c", "d"}


# ---------------------------------------------------------------------------
# Test imposé 7 — échec à mi-parcours : rollback, aucun état partiel
# ---------------------------------------------------------------------------


async def test_midway_failure_rolls_back(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import portal.db.mcp_catalog as cat_db

    async with db_engine.begin() as conn:
        await _seed(conn)
        await _resync(conn, {"a": "A", "b": "B"})

    real_upsert = cat_db.upsert_primitive
    calls = {"n": 0}

    async def _flaky(conn: AsyncConnection, **kw: Any) -> bool:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("boom mi-parcours")
        return await real_upsert(conn, **kw)

    monkeypatch.setattr(cat_db, "upsert_primitive", _flaky)

    with pytest.raises(RuntimeError, match="boom"):
        async with db_engine.begin() as conn:
            await _resync(conn, {"a": "A2", "b": "B2", "c": "C"})

    monkeypatch.setattr(cat_db, "upsert_primitive", real_upsert)
    async with db_engine.connect() as conn:
        # L'ancien registre est intact : ni définition modifiée, ni entrée partielle.
        prims = await list_primitives(conn, "b1", "tool")
        assert {p["original_name"] for p in prims} == {"a", "b"}
        by_name = {p["original_name"]: p for p in prims}
        assert by_name["a"]["definition"].get("description") == "A"
        assert all(not p["quarantined"] for p in prims)


# ---------------------------------------------------------------------------
# Test imposé 9 — deux resyncs concurrents du même backend
# ---------------------------------------------------------------------------


async def test_concurrent_resyncs_converge(
    db_engine: AsyncEngine, db_engine_concurrent: AsyncEngine
) -> None:
    async with db_engine.begin() as conn:
        await _seed(conn)
        await _resync(conn, {"a": "A", "old": "Old"})

    tools = {"a": "A", "b": "B", "c": "C"}

    async def _one_resync() -> None:
        async with db_engine_concurrent.begin() as conn:
            primitives, kinds = await fetch_backend_catalog(_session(tools))
            await write_backend_catalog(
                conn, backend_id="b1", primitives=primitives, kinds=kinds
            )

    await asyncio.gather(_one_resync(), _one_resync())

    async with db_engine.connect() as conn:
        prims = await list_primitives(conn, "b1", "tool")
        assert {p["original_name"] for p in prims} == {"a", "b", "c"}
        assert len(prims) == 3  # pas de doublons
        assert all(not p["quarantined"] for p in prims)


# ---------------------------------------------------------------------------
# Flag quarantine_disabled — plus de quarantaine sur redéfinition
# ---------------------------------------------------------------------------


async def test_protection_disabled_redefinition_stays_exposed(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _resync(db_conn, {"search": "v1"})

    result = await _resync(db_conn, {"search": "v2"}, protect_quarantine=False)
    assert result["quarantined"] == []
    prims = await list_primitives(db_conn, "b1", "tool")
    assert len(prims) == 1 and not prims[0]["quarantined"]
    assert prims[0]["definition"]["description"] == "v2"


async def test_protection_disabled_heals_previous_quarantine(db_conn: AsyncConnection) -> None:
    """Une quarantaine héritée d'un resync protégé est levée par un resync non protégé."""
    await _seed(db_conn)
    await _resync(db_conn, {"search": "v1"})
    result = await _resync(db_conn, {"search": "v2"})  # protégé → quarantaine
    assert result["quarantined"] == ["search"]

    result = await _resync(db_conn, {"search": "v2"}, protect_quarantine=False)
    assert result["quarantined"] == []
    prims = await list_primitives(db_conn, "b1", "tool")
    assert not prims[0]["quarantined"]


async def test_monitor_respects_backend_quarantine_flag(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed(db_conn, quarantine_disabled=True)
    await monitor_backend_once(db_conn, backend, open_session_fn=_session_fn({"search": "v1"}))

    await monitor_backend_once(db_conn, backend, open_session_fn=_session_fn({"search": "v2"}))
    prims = await list_primitives(db_conn, "b1", "tool")
    assert len(prims) == 1 and not prims[0]["quarantined"]


async def test_monitor_protects_by_default(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed(db_conn)  # quarantine_disabled=False
    await monitor_backend_once(db_conn, backend, open_session_fn=_session_fn({"search": "v1"}))

    await monitor_backend_once(db_conn, backend, open_session_fn=_session_fn({"search": "v2"}))
    prims = await list_primitives(db_conn, "b1", "tool")
    assert len(prims) == 1 and prims[0]["quarantined"]


# ---------------------------------------------------------------------------
# Instrumentation — log de resync avec delta nominatif
# ---------------------------------------------------------------------------


async def test_resync_logs_named_delta(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _resync(db_conn, {"a": "A", "b": "B"})

    with capture_logs() as logs:
        await _resync(db_conn, {"b": "B", "c": "C"}, trigger="probe")

    events = [e for e in logs if e["event"] == "mcp_catalog_resync"]
    assert len(events) == 1
    ev = events[0]
    assert ev["backend_id"] == "b1"
    assert ev["trigger"] == "probe"
    assert ev["before"] == 2 and ev["received"] == 2 and ev["after"] == 2
    assert ev["added"] == ["tool:c"]
    assert ev["removed"] == ["tool:a"]


async def test_resync_relogs_quarantine_every_pass(db_conn: AsyncConnection) -> None:
    """Une quarantaine active doit rester VISIBLE à chaque resync, pas seulement au flag."""
    await _seed(db_conn)
    await _resync(db_conn, {"search": "v1"})
    await _resync(db_conn, {"search": "v2"})  # → quarantaine

    with capture_logs() as logs:
        await _resync(db_conn, {"search": "v2"})  # hash stable, quarantaine collante

    events = [e for e in logs if e["event"] == "mcp_catalog_quarantined"]
    assert len(events) == 1
    assert events[0]["names"] == ["tool:search"]
