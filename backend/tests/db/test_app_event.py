"""Journal durable `app_event` : append / lecture par curseur / purge (DB réelle).

Exercent la couche DB pure (`portal.db.app_event`) via une connexion en SAVEPOINT
(`db_conn`, rollback après chaque test).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import app_event as j

_BASE = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


def _at(offset: int = 0) -> datetime:
    return _BASE + timedelta(seconds=offset)


@pytest.mark.asyncio
async def test_append_returns_increasing_seq(db_conn: AsyncConnection) -> None:
    s1 = await j.append(
        db_conn, event_id="e1", event_type="workspace.created", actor="alice", occurred_at=_at()
    )
    s2 = await j.append(
        db_conn, event_id="e2", event_type="workspace.stopped", actor="alice", occurred_at=_at(1)
    )
    assert s2 > s1


@pytest.mark.asyncio
async def test_append_persists_all_fields(db_conn: AsyncConnection) -> None:
    seq = await j.append(
        db_conn,
        event_id="e1",
        event_type="test_server.updated",
        actor="bob",
        occurred_at=_at(),
        workspace="devpod",
        subject={"address": "root@1.2.3.4"},
        correlation_id="op-1",
        dedup_key="k1",
    )
    row = await j.get(db_conn, seq)
    assert row is not None
    assert row["event_type"] == "test_server.updated"
    assert row["actor"] == "bob"
    assert row["workspace"] == "devpod"
    assert row["subject"] == {"address": "root@1.2.3.4"}
    assert row["correlation_id"] == "op-1"
    assert row["dedup_key"] == "k1"
    assert row["consumed_by"] is None


@pytest.mark.asyncio
async def test_get_missing_returns_none(db_conn: AsyncConnection) -> None:
    assert await j.get(db_conn, 999999) is None


@pytest.mark.asyncio
async def test_read_after_orders_and_limits(db_conn: AsyncConnection) -> None:
    seqs = [
        await j.append(
            db_conn, event_id=f"e{i}", event_type="session.created", actor="a", occurred_at=_at(i)
        )
        for i in range(5)
    ]
    got = await j.read_after(db_conn, after_seq=seqs[1], limit=2)
    assert [r["seq"] for r in got] == [seqs[2], seqs[3]]


@pytest.mark.asyncio
async def test_read_after_filters_by_type(db_conn: AsyncConnection) -> None:
    await j.append(
        db_conn, event_id="a", event_type="session.created", actor="a", occurred_at=_at()
    )
    b = await j.append(
        db_conn, event_id="b", event_type="workspace.created", actor="a", occurred_at=_at(1)
    )
    got = await j.read_after(db_conn, after_seq=0, limit=10, event_types=["workspace.created"])
    assert [r["seq"] for r in got] == [b]


@pytest.mark.asyncio
async def test_latest_seq_and_count_after(db_conn: AsyncConnection) -> None:
    assert await j.latest_seq(db_conn) == 0
    s1 = await j.append(
        db_conn, event_id="a", event_type="session.created", actor="a", occurred_at=_at()
    )
    s2 = await j.append(
        db_conn, event_id="b", event_type="session.closed", actor="a", occurred_at=_at(1)
    )
    assert await j.latest_seq(db_conn) == s2
    assert await j.count_after(db_conn, after_seq=s1) == 1
    assert await j.count_after(db_conn, after_seq=0, event_types=["session.created"]) == 1


@pytest.mark.asyncio
async def test_mark_consumed(db_conn: AsyncConnection) -> None:
    seq = await j.append(
        db_conn, event_id="a", event_type="session.created", actor="a", occurred_at=_at()
    )
    await j.mark_consumed(db_conn, seq=seq, consumer="automation:42")
    row = await j.get(db_conn, seq)
    assert row is not None
    assert row["consumed_by"] == "automation:42"


@pytest.mark.asyncio
async def test_purge_older_than(db_conn: AsyncConnection) -> None:
    await j.append(
        db_conn, event_id="a", event_type="session.created", actor="a", occurred_at=_at()
    )
    # created_at ≈ maintenant (server_default now()) : une borne passée ne purge rien,
    # une borne future purge tout.
    now = datetime.now(UTC)
    assert await j.purge_older_than(db_conn, older_than=now - timedelta(days=1)) == 0
    assert await j.purge_older_than(db_conn, older_than=now + timedelta(days=1)) == 1
    assert await j.latest_seq(db_conn) == 0


@pytest.mark.asyncio
async def test_list_recent_desc_and_pagination(db_conn: AsyncConnection) -> None:
    seqs = []
    for i in range(3):
        seqs.append(
            await j.append(
                db_conn,
                event_id=f"e{i}",
                event_type="user.created" if i == 1 else "workspace.created",
                actor="alice",
                occurred_at=_at(i),
            )
        )
    # Récent d'abord.
    recent = await j.list_recent(db_conn, limit=10)
    assert [r["seq"] for r in recent[:3]] == sorted(seqs, reverse=True)
    # Pagination par before_seq.
    page = await j.list_recent(db_conn, limit=10, before_seq=seqs[1])
    assert all(r["seq"] < seqs[1] for r in page)
    # Filtre multi-types (liste).
    typed = await j.list_recent(db_conn, limit=10, event_types=["user.created"])
    assert typed and all(r["event_type"] == "user.created" for r in typed)
    both = await j.list_recent(
        db_conn, limit=10, event_types=["user.created", "workspace.created"]
    )
    assert len(both) == 3
    assert await j.list_recent(db_conn, limit=10, event_types=[]) == recent
