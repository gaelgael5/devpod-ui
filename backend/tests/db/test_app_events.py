"""Couche db du journal d'événements applicatifs (app_event + livraisons)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portal.db import app_events as evdb

pytestmark = pytest.mark.asyncio


async def _insert(conn, event_id: str = "e1" * 16, actor: str = "alice") -> str:
    await evdb.insert_event(
        conn,
        event_id=event_id,
        event_type="workspace.created",
        actor=actor,
        workspace="mon-projet",
        subject={"ws_id": f"{actor}-mon-projet"},
        correlation_id=None,
        occurred_at=datetime.now(UTC),
    )
    return event_id


async def test_insert_et_list(db_conn) -> None:
    eid = await _insert(db_conn)
    rows = await evdb.list_events(db_conn, actor="alice")
    assert len(rows) == 1
    assert rows[0]["id"] == eid
    assert rows[0]["type"] == "workspace.created"
    assert rows[0]["subject"] == {"ws_id": "alice-mon-projet"}


async def test_list_filtre_par_acteur(db_conn) -> None:
    await _insert(db_conn, event_id="a" * 32, actor="alice")
    await _insert(db_conn, event_id="b" * 32, actor="bob")
    assert [r["actor"] for r in await evdb.list_events(db_conn, actor="bob")] == ["bob"]
    assert len(await evdb.list_events(db_conn)) == 2


async def test_livraisons(db_conn) -> None:
    eid = await _insert(db_conn)
    await evdb.insert_delivery(
        db_conn, event_id=eid, listener="docflow-bootstrap", status="ok", error=None
    )
    await evdb.insert_delivery(
        db_conn, event_id=eid, listener="autre", status="error", error="RuntimeError: x"
    )
    rows = await evdb.list_deliveries(db_conn, event_id=eid)
    assert {(r["listener"], r["status"]) for r in rows} == {
        ("docflow-bootstrap", "ok"),
        ("autre", "error"),
    }
