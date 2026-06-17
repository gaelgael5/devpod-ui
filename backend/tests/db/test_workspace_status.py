"""Tests de la couche persistance workspace_status (Tour 6)."""
from __future__ import annotations

import pytest

from portal.db.workspace_status import (
    delete_status_db,
    get_status_db,
    list_by_login_db,
    list_running_db,
    upsert_status_db,
)


@pytest.mark.asyncio
async def test_upsert_and_get(db_conn):
    await upsert_status_db("alice-ws", "provisioning", db_conn, login="alice")
    row = await get_status_db("alice-ws", db_conn)
    assert row is not None
    assert row["ws_id"] == "alice-ws"
    assert row["status"] == "provisioning"
    assert row["login"] == "alice"


@pytest.mark.asyncio
async def test_upsert_updates_existing(db_conn):
    await upsert_status_db("alice-ws", "provisioning", db_conn, login="alice")
    await upsert_status_db("alice-ws", "running", db_conn, login="alice", host_port=41000)
    row = await get_status_db("alice-ws", db_conn)
    assert row["status"] == "running"
    assert row["host_port"] == 41000


@pytest.mark.asyncio
async def test_get_unknown_returns_none(db_conn):
    row = await get_status_db("ghost", db_conn)
    assert row is None


@pytest.mark.asyncio
async def test_list_by_login_returns_own(db_conn):
    await upsert_status_db("alice-ws1", "running", db_conn, login="alice")
    await upsert_status_db("alice-ws2", "stopped", db_conn, login="alice")
    await upsert_status_db("bob-ws", "running", db_conn, login="bob")

    alice_rows = await list_by_login_db("alice", db_conn)
    assert len(alice_rows) == 2
    assert all(r["login"] == "alice" for r in alice_rows)


@pytest.mark.asyncio
async def test_list_running_only_running(db_conn):
    await upsert_status_db("ws-run", "running", db_conn, login="alice")
    await upsert_status_db("ws-stopped", "stopped", db_conn, login="alice")
    await upsert_status_db("ws-prov", "provisioning", db_conn, login="alice")

    rows = await list_running_db(db_conn)
    assert len(rows) == 1
    assert rows[0]["ws_id"] == "ws-run"


@pytest.mark.asyncio
async def test_delete_removes_row(db_conn):
    await upsert_status_db("alice-ws", "running", db_conn, login="alice")
    await delete_status_db("alice-ws", db_conn)
    row = await get_status_db("alice-ws", db_conn)
    assert row is None


@pytest.mark.asyncio
async def test_delete_nonexistent_no_error(db_conn):
    await delete_status_db("ghost", db_conn)


@pytest.mark.asyncio
async def test_extra_fields_stored(db_conn):
    await upsert_status_db(
        "alice-ws",
        "running",
        db_conn,
        login="alice",
        host_port=41000,
        host_type="ssh",
        host_name="worker-01",
        url="https://ws-alice-ws.dev.yoops.org",
        hostname="ws-alice-ws.dev.yoops.org",
    )
    row = await get_status_db("alice-ws", db_conn)
    assert row["host_port"] == 41000
    assert row["host_type"] == "ssh"
    assert row["host_name"] == "worker-01"
    assert row["url"] == "https://ws-alice-ws.dev.yoops.org"
    assert row["hostname"] == "ws-alice-ws.dev.yoops.org"


@pytest.mark.asyncio
async def test_failed_status_with_error(db_conn):
    await upsert_status_db(
        "alice-ws", "failed", db_conn, login="alice", returncode=1, error="TimeoutError"
    )
    row = await get_status_db("alice-ws", db_conn)
    assert row["status"] == "failed"
    assert row["returncode"] == 1
    assert row["error"] == "TimeoutError"
