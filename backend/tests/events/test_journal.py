"""`emit_event` journalise durablement dans `app_event` avant de diffuser sur le bus.

Vérifie : écriture au journal (chemin best-effort, `conn=None`), atomicité avec la
transaction de l'appelant (`conn` fourni), rejet silencieux d'un type inconnu, et
robustesse (le journal best-effort ne fait jamais échouer l'émission).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from portal.db.tables import app_event
from portal.events.bus import emit_event, get_bus, reset_bus


@pytest.fixture(autouse=True)
def _fresh_bus() -> None:
    reset_bus()
    yield
    reset_bus()


async def _rows(engine: AsyncEngine) -> list[dict]:
    async with engine.connect() as conn:
        return [dict(r) for r in (await conn.execute(select(app_event))).mappings().all()]


@pytest.mark.asyncio
async def test_emit_event_writes_to_journal(db_engine: AsyncEngine) -> None:
    await emit_event(
        "workspace.created",
        actor="alice",
        workspace="devpod",
        subject={"ws_id": "w1"},
        dedup_key="w1",
    )
    await get_bus().drain()
    rows = await _rows(db_engine)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "workspace.created"
    assert rows[0]["dedup_key"] == "w1"
    assert rows[0]["subject"] == {"ws_id": "w1"}


@pytest.mark.asyncio
async def test_emit_event_in_caller_txn_is_atomic(db_engine: AsyncEngine) -> None:
    # conn fourni : l'event partage la transaction de la mutation → un rollback l'annule.
    async with db_engine.connect() as conn:
        await conn.begin()
        await emit_event("session.created", actor="a", workspace="devpod", conn=conn)
        await conn.rollback()
    assert await _rows(db_engine) == []


@pytest.mark.asyncio
async def test_emit_event_unknown_type_is_ignored(db_engine: AsyncEngine) -> None:
    await emit_event("does.not.exist", actor="a")
    await get_bus().drain()
    assert await _rows(db_engine) == []


@pytest.mark.asyncio
async def test_emit_event_never_raises_when_journal_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Chemin best-effort : un moteur DB indisponible ne doit jamais faire échouer l'émission.
    import portal.db.engine as eng

    def _boom() -> None:
        raise RuntimeError("no engine")

    monkeypatch.setattr(eng, "_get_engine", _boom)
    await emit_event("workspace.created", actor="a")  # ne lève pas
    await get_bus().drain()
