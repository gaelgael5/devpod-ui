"""Mapping AppEvent → enveloppe plate normée (producteur workflow)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from portal.events.models import EVENT_TYPES, AppEvent
from portal.events.producer import to_envelope
from portal.events.schemas import EVENT_CODE_BY_TYPE


def _event(**kw: Any) -> AppEvent:
    base: dict[str, Any] = {
        "type": "workspace.created",
        "actor": "alice",
        "workspace": "proj",
        "subject": {"ws_id": "alice-proj", "node": "n1"},
    }
    base.update(kw)
    return AppEvent(**base)


def test_envelope_system_fields() -> None:
    ev = _event()
    env = to_envelope(ev, source_uri="urn:yoops:devpod")
    assert env["_eventId"] == str(uuid.UUID(ev.event_id))  # UUID canonique à tirets
    assert env["_eventCode"] == "devpod.workspace.created.v1"
    assert env["_source"] == "urn:yoops:devpod"
    assert env["_specVersion"] == "1.0"
    parsed = datetime.fromisoformat(env["_occurredAt"])
    assert parsed.tzinfo is not None  # RFC 3339 avec timezone


def test_envelope_business_fields_flat_at_root() -> None:
    env = to_envelope(_event(), source_uri="s")
    assert env["actor"] == "alice"
    assert env["workspace"] == "proj"
    assert env["ws_id"] == "alice-proj"
    assert env["node"] == "n1"
    # Enveloppe plate : pas de wrapper `data`/`subject`.
    assert "data" not in env
    assert "subject" not in env


def test_trace_id_optional_from_correlation() -> None:
    assert to_envelope(_event(correlation_id="op-123"), source_uri="s")["_traceId"] == "op-123"
    assert "_traceId" not in to_envelope(_event(), source_uri="s")


def test_workspace_omitted_when_none() -> None:
    ev = _event(
        type="compose_service.started",
        workspace=None,
        subject={
            "deployment_uid": "d",
            "deployment_id": "dep",
            "template_id": "t",
            "node_id": "n",
            "action": "up",
        },
    )
    env = to_envelope(ev, source_uri="s")
    assert "workspace" not in env
    assert env["action"] == "up"


def test_underscore_subject_key_never_overrides_system_space() -> None:
    # Un subject hostile ne doit pas pouvoir écraser un champ système.
    ev = _event(subject={"_eventCode": "evil", "ws_id": "x", "node": "n"})
    env = to_envelope(ev, source_uri="s")
    assert env["_eventCode"] == "devpod.workspace.created.v1"


def test_all_event_types_have_a_code() -> None:
    for t in EVENT_TYPES:
        assert EVENT_CODE_BY_TYPE[t] == f"devpod.{t}.v1"
