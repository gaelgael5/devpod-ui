"""Toggle à chaud + liste blanche du relais workflow (reconcile_workflow_producer).

Le relais est (dé)branché du bus selon la config courante — c'est ce qui rend le
paramètre `enabled` et la liste blanche `events` effectifs sans redémarrage.
"""

from __future__ import annotations

import types

import pytest

import portal.config.store as store
import portal.events.bus as bus_mod
from portal.config.models import EventsProducerConfig
from portal.events.bus import EventBus
from portal.events.egress import WORKFLOW_PRODUCER, reconcile_workflow_producer


def _cfg(**kw: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(events_producer=EventsProducerConfig(**kw))


class TestBusUnsubscribe:
    def test_removes_and_is_idempotent(self) -> None:
        bus = EventBus()

        async def h(e: object) -> None:
            return None

        bus.subscribe("x", ["workspace.created"], h)
        assert bus.has_subscriber("x")
        assert bus.unsubscribe("x") is True
        assert bus.has_subscriber("x") is False
        assert bus.unsubscribe("x") is False  # idempotent


class TestReconcile:
    @pytest.fixture(autouse=True)
    def _fresh_bus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bus = EventBus()
        monkeypatch.setattr(bus_mod, "get_bus", lambda: self.bus)

    def _set(self, monkeypatch: pytest.MonkeyPatch, **kw: object) -> None:
        monkeypatch.setattr(store, "load_global", lambda: _cfg(**kw))

    def test_disabled_no_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set(monkeypatch, enabled=False, events=["workspace.created"])
        assert reconcile_workflow_producer() == []
        assert not self.bus.has_subscriber(WORKFLOW_PRODUCER)

    def test_enabled_subscribes_allowlist_intersected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set(
            monkeypatch, enabled=True, events=["workspace.created", "zzz.unknown", "session.closed"]
        )
        got = reconcile_workflow_producer()
        assert got == ["session.closed", "workspace.created"]  # trié, type inconnu écarté
        assert self.bus.has_subscriber(WORKFLOW_PRODUCER)

    def test_enabled_but_empty_allowlist_stays_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set(monkeypatch, enabled=True, events=[])
        assert reconcile_workflow_producer() == []
        assert not self.bus.has_subscriber(WORKFLOW_PRODUCER)

    def test_toggle_off_unsubscribes_live(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set(monkeypatch, enabled=True, events=["workspace.created"])
        reconcile_workflow_producer()
        assert self.bus.has_subscriber(WORKFLOW_PRODUCER)
        self._set(monkeypatch, enabled=False, events=["workspace.created"])
        reconcile_workflow_producer()
        assert not self.bus.has_subscriber(WORKFLOW_PRODUCER)

    def test_reconcile_is_idempotent_no_duplicate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set(monkeypatch, enabled=True, events=["workspace.created"])
        reconcile_workflow_producer()
        reconcile_workflow_producer()  # ne doit pas lever (déjà abonné) ni dupliquer
        assert self.bus.has_subscriber(WORKFLOW_PRODUCER)
