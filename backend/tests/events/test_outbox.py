"""Outbox transactionnel du relais workflow : backoff, livraison unitaire, enqueue.

Les tests sont purs (pas de DB Postgres, indisponible en local) : `enqueue_event`
monkeypatche la couche DB et l'engine pour capturer ce qui serait inséré, et
`deliver_one` s'appuie sur `httpx.MockTransport`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from portal.events import egress
from portal.events.egress import (
    MAX_ATTEMPTS,
    _backoff_seconds,
    compute_signature,
    deliver_one,
    enqueue_event,
    serialize_envelope,
)
from portal.events.models import AppEvent
from portal.events.producer import to_envelope


def _event() -> AppEvent:
    return AppEvent(
        type="workspace.created",
        actor="alice",
        workspace="proj",
        subject={"ws_id": "alice-proj", "node": "n1"},
    )


class TestBackoff:
    def test_increases_then_caps_at_3600(self) -> None:
        seq = [_backoff_seconds(n) for n in range(0, 12)]
        # Croissant tant que non plafonné.
        rising = [v for v in seq if v < 3600.0]
        assert rising == sorted(rising)
        assert rising[0] == 30.0  # 30 * 2**0
        # Plafonné à 3600 et jamais dépassé.
        assert max(seq) == 3600.0
        assert _backoff_seconds(MAX_ATTEMPTS) == 3600.0


def _row(raw_body: str = '{"x":1}', attempts: int = 0) -> dict[str, Any]:
    return {"id": 1, "raw_body": raw_body, "attempts": attempts}


async def _deliver(status_or_exc: Any) -> tuple[str, str | None]:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(status_or_exc, Exception):
            raise status_or_exc
        return httpx.Response(status_or_exc)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        return await deliver_one(
            _row(),
            base_url="https://wf.example",
            source_id="src-1",
            secret="topsecret",
            client=client,
        )


class TestDeliverOne:
    async def test_202_is_delivered(self) -> None:
        outcome, error = await _deliver(202)
        assert outcome == "delivered"
        assert error is None

    async def test_500_is_not_delivered_with_message(self) -> None:
        outcome, error = await _deliver(500)
        assert outcome != "delivered"
        assert error is not None
        assert "500" in error

    async def test_connect_error_does_not_propagate(self) -> None:
        outcome, error = await _deliver(httpx.ConnectError("boom"))
        assert outcome != "delivered"
        assert error is not None

    async def test_secret_never_leaks_in_error(self) -> None:
        secret = "supersecretvalue"

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            _outcome, error = await deliver_one(
                _row(),
                base_url="https://wf.example",
                source_id="src-1",
                secret=secret,
                client=client,
            )
        assert error is not None
        assert secret not in error

    async def test_signature_is_computed_on_posted_bytes(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["sig"] = request.headers.get("x-signature")
            seen["body"] = request.content
            return httpx.Response(202)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await deliver_one(
                _row(raw_body='{"a":"é"}'),
                base_url="https://wf.example",
                source_id="src-1",
                secret="k",
                client=client,
            )
        assert seen["body"] == '{"a":"é"}'.encode()
        assert seen["sig"] == compute_signature(b"k", seen["body"])


class _Cfg:
    enabled = True
    workflow_base_url = "https://wf.example"
    source_id = "src-1"
    secret_slug = "workflow_events_hmac"
    source_uri = "urn:yoops:devpod"


class _Global:
    events_producer = _Cfg()


class _FakeConn:
    pass


class _FakeEngine:
    @asynccontextmanager
    async def _cm(self) -> Any:
        yield _FakeConn()

    def begin(self) -> Any:
        return self._cm()


class TestEnqueueEvent:
    async def test_inserts_exact_serialized_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        monkeypatch.setattr("portal.config.store.load_global", lambda: _Global())
        monkeypatch.setattr("portal.db.engine._get_engine", lambda: _FakeEngine())

        async def _enqueue(conn: object, *, event_id: str, event_code: str, raw_body: str) -> None:
            captured.update(event_id=event_id, event_code=event_code, raw_body=raw_body)

        monkeypatch.setattr("portal.db.workflow_outbox.enqueue", _enqueue)

        event = _event()
        result = await enqueue_event(event)

        expected_envelope = to_envelope(event, source_uri=_Cfg.source_uri)
        expected_raw = serialize_envelope(expected_envelope)

        # Ce qui est mis en file == octets exacts qui seront signés ET postés.
        assert captured["raw_body"] == expected_raw.decode()
        assert captured["event_code"] == expected_envelope["_eventCode"]
        assert captured["event_id"] == expected_envelope["_eventId"]
        assert result == {"event_code": expected_envelope["_eventCode"], "outbox": "queued"}


def test_reconcile_still_exported() -> None:
    # Garde-fou : l'API publique (importée par app.py et routes/admin.py) est conservée.
    assert hasattr(egress, "reconcile_workflow_producer")
    assert egress.WORKFLOW_PRODUCER == "workflow-producer"
