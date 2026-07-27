"""Bus d'événements : dispatch ciblé par type, isolation des échecs d'écouteur."""

from __future__ import annotations

import pytest

from portal.events.bus import EventBus, emit_event, get_bus, reset_bus
from portal.events.models import AppEvent


def _event(event_type: str = "workspace.created") -> AppEvent:
    return AppEvent(type=event_type, actor="alice", workspace="ws1")


async def test_dispatch_cible_par_type() -> None:
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


async def test_echec_ecouteur_isole() -> None:
    """Un écouteur qui lève n'empêche ni emit() ni les écouteurs suivants."""
    bus = EventBus()
    received: list[str] = []

    async def boom(event: AppEvent) -> None:
        raise RuntimeError("kaputt")

    async def ok(event: AppEvent) -> None:
        received.append("ok")

    bus.subscribe("l-boom", ["workspace.created"], boom)
    bus.subscribe("l-ok", ["workspace.created"], ok)

    await bus.emit(_event())  # ne doit jamais lever
    await bus.drain()

    assert received == ["ok"]


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


async def test_unsubscribe_idempotent() -> None:
    bus = EventBus()

    async def handler(event: AppEvent) -> None:  # pragma: no cover
        pass

    bus.subscribe("l", ["workspace.created"], handler)
    assert bus.has_subscriber("l") is True
    assert bus.unsubscribe("l") is True
    assert bus.has_subscriber("l") is False
    assert bus.unsubscribe("l") is False


async def test_emit_event_type_invalide_n_leve_pas() -> None:
    """emit_event est fire-and-forget : jamais d'exception vers l'opération métier."""
    reset_bus()
    received: list[AppEvent] = []

    async def handler(event: AppEvent) -> None:  # pragma: no cover
        received.append(event)

    get_bus().subscribe("l", ["workspace.created"], handler)
    await emit_event("n.importe.quoi", actor="alice")  # type invalide → aucun dispatch
    await get_bus().drain()
    assert received == []
    reset_bus()


async def test_emit_event_via_singleton() -> None:
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
