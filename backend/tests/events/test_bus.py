"""Bus d'événements : dispatch ciblé, isolation des échecs, journalisation."""

from __future__ import annotations

from typing import Any

import pytest

import portal.events.bus as bus_mod
from portal.events.bus import EventBus, emit_event, get_bus, reset_bus
from portal.events.models import AppEvent


@pytest.fixture()
def journal(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Neutralise la persistance DB et enregistre les appels."""
    calls: dict[str, list[Any]] = {"events": [], "deliveries": []}

    async def fake_persist_event(event: AppEvent) -> None:
        calls["events"].append(event)

    async def fake_persist_delivery(
        event_id: str, listener: str, status: str, error: str | None, detail: Any = None
    ) -> None:
        calls["deliveries"].append((event_id, listener, status, error, detail))

    monkeypatch.setattr(bus_mod, "_persist_event", fake_persist_event)
    monkeypatch.setattr(bus_mod, "_persist_delivery", fake_persist_delivery)
    return calls


def _event(event_type: str = "workspace.created") -> AppEvent:
    return AppEvent(type=event_type, actor="alice", workspace="ws1")


async def test_dispatch_cible_par_type(journal: dict[str, list[Any]]) -> None:
    bus = EventBus()
    received: list[str] = []

    async def on_created(event: AppEvent) -> None:
        received.append(f"created:{event.workspace}")

    async def on_deleted(event: AppEvent) -> None:
        received.append("deleted")

    bus.subscribe("l-created", ["workspace.created"], on_created)
    bus.subscribe("l-deleted", ["workspace.deleted"], on_deleted)

    await bus.emit(_event())
    await bus.drain()

    assert received == ["created:ws1"]
    assert len(journal["events"]) == 1
    assert journal["deliveries"] == [(journal["events"][0].event_id, "l-created", "ok", None, None)]


async def test_echec_ecouteur_isole(journal: dict[str, list[Any]]) -> None:
    """Un écouteur qui lève n'empêche ni emit() ni les écouteurs suivants."""
    bus = EventBus()
    received: list[str] = []

    async def boom(event: AppEvent) -> None:
        raise RuntimeError("kaputt")

    async def ok(event: AppEvent) -> None:
        received.append("ok")

    bus.subscribe("l-boom", ["workspace.created"], boom)
    bus.subscribe("l-ok", ["workspace.created"], ok)

    await bus.emit(_event())
    await bus.drain()

    assert received == ["ok"]
    statuses = {(listener, status) for _, listener, status, _, _ in journal["deliveries"]}
    assert statuses == {("l-boom", "error"), ("l-ok", "ok")}
    error = next(err for _, listener, _, err, _ in journal["deliveries"] if listener == "l-boom")
    assert error is not None and "kaputt" in error


async def test_detail_retourne_par_le_handler_journalise(journal: dict[str, list[Any]]) -> None:
    bus = EventBus()

    async def handler(event: AppEvent) -> list[dict[str, Any]]:
        return [{"rule": "r1", "matched": True, "actions_ran": 2}]

    bus.subscribe("l", ["workspace.created"], handler)
    await bus.emit(_event())
    await bus.drain()
    _, _, status, _, detail = journal["deliveries"][0]
    assert status == "ok"
    assert detail == [{"rule": "r1", "matched": True, "actions_ran": 2}]


async def test_detail_porte_par_l_exception_journalise(journal: dict[str, list[Any]]) -> None:
    """Même en échec, le détail par règle attaché à l'exception est journalisé."""
    bus = EventBus()

    async def handler(event: AppEvent) -> None:
        exc = RuntimeError("une règle a échoué")
        exc.delivery_detail = [{"rule": "r1", "error": "boom"}]  # type: ignore[attr-defined]
        raise exc

    bus.subscribe("l", ["workspace.created"], handler)
    await bus.emit(_event())
    await bus.drain()
    _, _, status, error, detail = journal["deliveries"][0]
    assert status == "error"
    assert error is not None and "une règle a échoué" in error
    assert detail == [{"rule": "r1", "error": "boom"}]


async def test_echec_journal_n_empeche_pas_le_dispatch(
    monkeypatch: pytest.MonkeyPatch, journal: dict[str, list[Any]]
) -> None:
    async def broken_persist(event: AppEvent) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(bus_mod, "_persist_event", broken_persist)
    bus = EventBus()
    received: list[AppEvent] = []

    async def handler(event: AppEvent) -> None:
        received.append(event)

    bus.subscribe("l", ["workspace.created"], handler)
    await bus.emit(_event())  # ne doit pas lever
    await bus.drain()
    assert len(received) == 1


def test_subscribe_type_inconnu_rejete() -> None:
    bus = EventBus()

    async def handler(event: AppEvent) -> None:  # pragma: no cover
        pass

    with pytest.raises(ValueError):
        bus.subscribe("l", ["workspace.exploded"], handler)


def test_subscribe_nom_duplique_rejete() -> None:
    bus = EventBus()

    async def handler(event: AppEvent) -> None:  # pragma: no cover
        pass

    bus.subscribe("l", ["workspace.created"], handler)
    with pytest.raises(ValueError):
        bus.subscribe("l", ["workspace.deleted"], handler)


async def test_emit_event_type_invalide_n_leve_pas(journal: dict[str, list[Any]]) -> None:
    """emit_event est fire-and-forget : jamais d'exception vers l'opération métier."""
    reset_bus()
    await emit_event("n.importe.quoi", actor="alice")
    assert journal["events"] == []


async def test_emit_event_via_singleton(journal: dict[str, list[Any]]) -> None:
    reset_bus()
    received: list[AppEvent] = []

    async def handler(event: AppEvent) -> None:
        received.append(event)

    get_bus().subscribe("l", ["session.created"], handler)
    await emit_event("session.created", actor="alice", workspace="ws1", subject={"session": "main"})
    await get_bus().drain()
    assert len(received) == 1
    assert received[0].subject == {"session": "main"}
    reset_bus()
