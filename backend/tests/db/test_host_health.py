"""Couche DB de la vivacité des hosts (enabler 727ee81d) — host_health."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.host_health import (
    get_all,
    prune_absent,
    record_success,
    record_unreachable,
)


async def test_record_success_inserts_then_updates(db_conn: AsyncConnection) -> None:
    t1 = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    await record_success(db_conn, "node1", t1, transitioned=True)
    rows = await get_all(db_conn)
    assert rows["node1"]["reachable"] is True
    assert rows["node1"]["last_seen"] == t1
    assert rows["node1"]["changed_at"] == t1

    # Tick suivant sans transition : last_seen avance, changed_at reste figé.
    t2 = datetime(2026, 7, 26, 10, 1, tzinfo=UTC)
    await record_success(db_conn, "node1", t2, transitioned=False)
    rows = await get_all(db_conn)
    assert rows["node1"]["last_seen"] == t2
    assert rows["node1"]["changed_at"] == t1


async def test_record_unreachable_keeps_last_seen(db_conn: AsyncConnection) -> None:
    t1 = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 26, 10, 5, tzinfo=UTC)
    await record_success(db_conn, "node1", t1, transitioned=True)
    await record_unreachable(db_conn, "node1", t2)
    rows = await get_all(db_conn)
    assert rows["node1"]["reachable"] is False
    assert rows["node1"]["changed_at"] == t2
    # last_seen = dernière sonde RÉUSSIE : précieux pour dater la disparition.
    assert rows["node1"]["last_seen"] == t1


async def test_prune_absent_removes_only_unknown(db_conn: AsyncConnection) -> None:
    t = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    await record_success(db_conn, "node1", t, transitioned=True)
    await record_success(db_conn, "node2", t, transitioned=True)
    await prune_absent(db_conn, {"node1"})
    rows = await get_all(db_conn)
    assert set(rows) == {"node1"}
