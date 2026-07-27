"""Couche DB des périodes d'inactivité (enabler 6016436b) — workspace_idle."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.workspace_idle import (
    clear,
    get_all,
    get_for_ws,
    mark_alerted,
    upsert_idle,
)

_T0 = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


async def test_upsert_preserves_alert_by_default(db_conn: AsyncConnection) -> None:
    since = _T0 - timedelta(hours=5)
    await upsert_idle(db_conn, "alice-dev", "alice", since, since, _T0)
    await mark_alerted(db_conn, "alice-dev", _T0)

    await upsert_idle(db_conn, "alice-dev", "alice", since, since, _T0 + timedelta(minutes=5))
    row = await get_for_ws(db_conn, "alice-dev")
    assert row is not None
    assert row["alerted_at"] is not None  # une seule alerte par période continue


async def test_upsert_reset_alert_rearms(db_conn: AsyncConnection) -> None:
    since = _T0 - timedelta(hours=5)
    await upsert_idle(db_conn, "alice-dev", "alice", since, since, _T0)
    await mark_alerted(db_conn, "alice-dev", _T0)

    recent = _T0 - timedelta(minutes=10)
    await upsert_idle(db_conn, "alice-dev", "alice", recent, recent, _T0, reset_alert=True)
    row = await get_for_ws(db_conn, "alice-dev")
    assert row is not None
    assert row["alerted_at"] is None
    assert row["idle_since"] == recent


async def test_clear_and_get_all(db_conn: AsyncConnection) -> None:
    await upsert_idle(db_conn, "alice-dev", "alice", _T0, None, _T0)
    await upsert_idle(db_conn, "bob-ml", "bob", _T0, None, _T0)
    assert set(await get_all(db_conn)) == {"alice-dev", "bob-ml"}
    await clear(db_conn, ["alice-dev"])
    assert set(await get_all(db_conn)) == {"bob-ml"}
    await clear(db_conn, [])  # no-op sûr
    assert await get_for_ws(db_conn, "alice-dev") is None
