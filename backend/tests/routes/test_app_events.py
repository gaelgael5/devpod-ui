"""Endpoints REST du journal d'événements — jointure livraisons + garde replay."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import portal.routes.app_events as rt

USER = type("U", (), {"login": "alice"})()
CONN = object()

_NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def _event_row(event_id: str = "e" * 32, actor: str = "alice") -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "workspace.created",
        "actor": actor,
        "workspace": "mon-projet",
        "subject": {"ws_id": f"{actor}-mon-projet"},
        "correlation_id": None,
        "occurred_at": _NOW,
    }


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(rt.db, "list_events", m.list_events)
    monkeypatch.setattr(rt.db, "list_deliveries_for_events", m.list_deliveries_for_events)
    monkeypatch.setattr(rt.db, "get_event", m.get_event)
    return m


@pytest.mark.asyncio
async def test_list_joint_les_livraisons(db: AsyncMock) -> None:
    db.list_events.return_value = [_event_row()]
    db.list_deliveries_for_events.return_value = [
        {"id": 1, "event_id": "e" * 32, "listener": "docflow-bootstrap", "status": "error",
         "error": "AutomationError: x", "finished_at": _NOW},
    ]
    out = await rt.list_events_route(workspace=None, limit=50, user=USER, conn=CONN)
    assert len(out) == 1
    assert out[0]["deliveries"][0]["listener"] == "docflow-bootstrap"
    db.list_events.assert_awaited_once_with(CONN, actor="alice", workspace=None, limit=50)


@pytest.mark.asyncio
async def test_list_evenement_sans_livraison(db: AsyncMock) -> None:
    db.list_events.return_value = [_event_row()]
    db.list_deliveries_for_events.return_value = []
    out = await rt.list_events_route(workspace=None, limit=50, user=USER, conn=CONN)
    assert out[0]["deliveries"] == []


@pytest.mark.asyncio
async def test_replay_redispatche_via_le_bus(
    db: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.get_event.return_value = _event_row()
    redelivered: list[Any] = []

    class _Bus:
        async def redeliver(self, event: Any) -> None:
            redelivered.append(event)

    monkeypatch.setattr(rt, "get_bus", lambda: _Bus())
    out = await rt.replay_event_route("e" * 32, user=USER, conn=CONN)
    assert out == {"replayed": "e" * 32}
    assert len(redelivered) == 1
    assert redelivered[0].type == "workspace.created"
    assert redelivered[0].event_id == "e" * 32


@pytest.mark.asyncio
async def test_replay_404_si_inconnu(db: AsyncMock) -> None:
    db.get_event.return_value = None
    with pytest.raises(HTTPException) as e:
        await rt.replay_event_route("e" * 32, user=USER, conn=CONN)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_replay_404_si_autre_utilisateur(db: AsyncMock) -> None:
    """L'événement d'un autre utilisateur est indistinguable d'un événement absent."""
    db.get_event.return_value = _event_row(actor="bob")
    with pytest.raises(HTTPException) as e:
        await rt.replay_event_route("e" * 32, user=USER, conn=CONN)
    assert e.value.status_code == 404
