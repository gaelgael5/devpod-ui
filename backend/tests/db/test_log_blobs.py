"""Tests de la couche DB workspace_log_blobs (Tour 9)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.log_blobs import (
    delete_log_blobs,
    get_latest_log_blob,
    list_log_blobs,
    persist_log_blob_from_file,
)

pytestmark = pytest.mark.asyncio


async def _insert_blob(
    conn: AsyncConnection,
    ws_id: str = "alice-myws",
    login: str = "alice",
    operation: str = "up",
    content: str = "log content",
) -> None:
    from sqlalchemy import insert

    from portal.db.tables import workspace_log_blobs

    await conn.execute(
        insert(workspace_log_blobs).values(
            ws_id=ws_id, login=login, operation=operation, content=content
        )
    )


async def test_list_empty(db_conn: AsyncConnection) -> None:
    results = await list_log_blobs("alice-myws", db_conn)
    assert results == []


async def test_persist_and_list(db_conn: AsyncConnection, tmp_path) -> None:
    log_file = tmp_path / "test.log"
    log_file.write_text("line1\nline2\n", encoding="utf-8")
    await persist_log_blob_from_file("alice-myws", "alice", "up", log_file, db_conn)

    blobs = await list_log_blobs("alice-myws", db_conn)
    assert len(blobs) == 1
    assert blobs[0]["content"] == "line1\nline2\n"
    assert blobs[0]["operation"] == "up"
    assert blobs[0]["ws_id"] == "alice-myws"
    assert blobs[0]["finished_at"] is not None


async def test_persist_missing_file(db_conn: AsyncConnection, tmp_path) -> None:
    missing = tmp_path / "nonexistent.log"
    await persist_log_blob_from_file("alice-myws", "alice", "stop", missing, db_conn)

    blobs = await list_log_blobs("alice-myws", db_conn)
    assert len(blobs) == 1
    assert blobs[0]["content"] == ""


async def test_get_latest(db_conn: AsyncConnection) -> None:
    await _insert_blob(db_conn, content="first up")
    await _insert_blob(db_conn, content="second up")
    result = await get_latest_log_blob("alice-myws", "up", db_conn)
    assert result is not None


async def test_get_latest_unknown_ws_returns_none(db_conn: AsyncConnection) -> None:
    result = await get_latest_log_blob("ghost-ws", "up", db_conn)
    assert result is None


async def test_delete_blobs(db_conn: AsyncConnection) -> None:
    await _insert_blob(db_conn)
    await _insert_blob(db_conn, operation="stop")
    await delete_log_blobs("alice-myws", db_conn)
    assert await list_log_blobs("alice-myws", db_conn) == []


async def test_delete_nonexistent_no_error(db_conn: AsyncConnection) -> None:
    await delete_log_blobs("ghost-ws", db_conn)


async def test_multiple_workspaces_isolated(db_conn: AsyncConnection) -> None:
    await _insert_blob(db_conn, ws_id="alice-ws1", login="alice", content="ws1 log")
    await _insert_blob(db_conn, ws_id="alice-ws2", login="alice", content="ws2 log")

    ws1 = await list_log_blobs("alice-ws1", db_conn)
    ws2 = await list_log_blobs("alice-ws2", db_conn)
    assert len(ws1) == 1 and ws1[0]["content"] == "ws1 log"
    assert len(ws2) == 1 and ws2[0]["content"] == "ws2 log"
