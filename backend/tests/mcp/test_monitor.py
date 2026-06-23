from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import mcp_backend, users
from portal.mcp.connections import BackendUnavailable
from portal.mcp.monitor import (
    BackendHealth,
    get_health,
    health_snapshot,
    monitor_backend_once,
    reset_health,
    set_health,
)


def test_get_health_unknown_by_default() -> None:
    reset_health()
    assert get_health("b1") == BackendHealth(status="unknown")


def test_set_and_get_health() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    set_health("b2", BackendHealth(status="down", error="boom"))
    assert get_health("b1").status == "up"
    assert get_health("b2") == BackendHealth(status="down", error="boom")


def test_health_snapshot_is_copy() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    snap = health_snapshot()
    set_health("b2", BackendHealth(status="up"))
    assert "b2" not in snap  # snapshot pris avant n'est pas muté
    assert snap["b1"].status == "up"


# ---------------------------------------------------------------------------
# monitor_backend_once
# ---------------------------------------------------------------------------


def _fake_backend() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        return text

    return srv


def _patched_open_session(server: FastMCP):
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _factory


async def _seed_backend(conn: AsyncConnection) -> dict:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(insert(mcp_backend).values(
        id="b1", owner_login="alice", namespace="rag", name="RAG",
        url="https://rag/mcp", transport="streamable_http", enabled=True))
    return {"id": "b1", "owner_login": "alice", "namespace": "rag", "name": "RAG",
            "url": "https://rag/mcp", "transport": "streamable_http", "enabled": True}


async def test_monitor_backend_once_up(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed_backend(db_conn)
    health = await monitor_backend_once(
        db_conn, backend, open_session_fn=_patched_open_session(_fake_backend())
    )
    assert health.status == "up"
    assert get_health("b1").status == "up"
    # le catalogue a été synchronisé
    from portal.db.mcp_catalog import list_primitives
    assert len(await list_primitives(db_conn, "b1", "tool")) == 1


async def test_monitor_backend_once_down(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed_backend(db_conn)

    @asynccontextmanager
    async def _unavailable(url: str, *, bearer: str | None = None, **kw):
        raise BackendUnavailable("down", backend_id="b1")
        yield  # noqa: RET504  # unreachable, fait du factory un générateur

    health = await monitor_backend_once(db_conn, backend, open_session_fn=_unavailable)
    assert health.status == "down" and health.error is not None
    assert get_health("b1").status == "down"
