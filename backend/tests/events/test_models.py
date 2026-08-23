"""Contrat de l'enveloppe AppEvent : registre fermé, défauts, extra interdit."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from portal.events.models import EVENT_TYPES, AppEvent


def test_type_inconnu_rejete() -> None:
    with pytest.raises(ValidationError):
        AppEvent(type="workspace.exploded", actor="alice")


def test_registre_contient_les_types_attendus() -> None:
    assert {
        "user.created",
        "user.refreshed",
        "user.connected",
        "user.disconnected",
        "user.deleted",
        "user.paused",
        "user.resumed",
        "workspace.created",
        "workspace.updated",
        "workspace.deleted",
        "workspace.stopped",
        "workspace.restarted",
        "session.created",
        "session.closed",
        "test_server.created",
        "test_server.updated",
        "test_server.deleted",
        "compose_service.started",
        "compose_service.stopped",
        "skill.available",
    } == EVENT_TYPES


def test_defauts_enveloppe() -> None:
    ev = AppEvent(type="workspace.created", actor="alice")
    assert len(ev.event_id) == 32 and all(c in "0123456789abcdef" for c in ev.event_id)
    assert ev.occurred_at.tzinfo is UTC
    assert ev.workspace is None
    assert ev.subject == {}
    assert ev.correlation_id is None


def test_extra_interdit() -> None:
    with pytest.raises(ValidationError):
        AppEvent(type="workspace.created", actor="alice", payload={})  # type: ignore[call-arg]
