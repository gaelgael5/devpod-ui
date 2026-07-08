"""Egress signé vers le workflow : signature, sérialisation, POST, écouteur."""

from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any

import httpx
import pytest

from portal.events import egress
from portal.events.egress import (
    EgressError,
    compute_signature,
    forward_to_workflow,
    post_event,
    serialize_envelope,
)
from portal.events.models import AppEvent


def test_compute_signature_matches_workflow_algo() -> None:
    secret, body = b"shhh", b'{"_eventId":"x"}'
    # Doit reproduire exactement hmac.new(secret, raw, sha256).hexdigest() côté workflow.
    assert compute_signature(secret, body) == hmac.new(secret, body, sha256).hexdigest()


def test_serialize_is_utf8_and_roundtrips() -> None:
    raw = serialize_envelope({"a": 1, "b": "é"})
    assert json.loads(raw) == {"a": 1, "b": "é"}
    assert b"\\u00e9" not in raw  # ensure_ascii=False : pas d'échappement unicode


async def test_post_event_sends_signed_raw_body_to_ingestion_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["sig"] = request.headers.get("x-signature")
        seen["body"] = request.content
        return httpx.Response(202)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await post_event(
            "https://wf.example/", "src-1", b'{"x":1}', "deadbeef", client=client
        )

    assert status == 202
    assert seen["url"] == "https://wf.example/events/src-1"
    assert seen["sig"] == "deadbeef"
    assert seen["body"] == b'{"x":1}'


class _Cfg:
    enabled = True
    workflow_base_url = "https://wf.example"
    source_id = "src-1"
    secret_slug = "workflow_events_hmac"
    source_uri = "urn:yoops:devpod"


class _Global:
    events_producer = _Cfg()


class _FakeEngine:
    @asynccontextmanager
    async def _cm(self) -> Any:
        yield object()

    def connect(self) -> Any:
        return self._cm()


def _wire(monkeypatch: pytest.MonkeyPatch, *, status: int) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    monkeypatch.setattr("portal.config.store.load_global", lambda: _Global())
    monkeypatch.setattr("portal.db.engine._get_engine", lambda: _FakeEngine())

    async def _reveal(slug: str, conn: object) -> str:
        captured["slug"] = slug
        return "topsecret"

    monkeypatch.setattr("portal.secrets.system.reveal_system_secret", _reveal)

    async def _post(base: str, sid: str, raw: bytes, sig: str) -> int:
        captured.update(base=base, sid=sid, raw=raw, sig=sig)
        return status

    monkeypatch.setattr(egress, "post_event", _post)
    return captured


def _event() -> AppEvent:
    return AppEvent(
        type="workspace.created",
        actor="alice",
        workspace="proj",
        subject={"ws_id": "alice-proj", "node": "n1"},
    )


async def test_forward_delivers_and_signs_the_posted_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _wire(monkeypatch, status=202)
    detail = await forward_to_workflow(_event())

    assert detail["status_code"] == 202
    assert detail["event_code"] == "devpod.workspace.created.v1"
    assert captured["base"] == "https://wf.example"
    assert captured["sid"] == "src-1"
    assert captured["slug"] == "workflow_events_hmac"
    # La signature postée correspond aux octets bruts effectivement postés.
    assert captured["sig"] == compute_signature(b"topsecret", captured["raw"])


async def test_forward_raises_on_non_202(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, status=401)
    with pytest.raises(EgressError) as exc:
        await forward_to_workflow(_event())
    # Le détail est journalisé par le bus (delivery_detail).
    assert exc.value.delivery_detail == {
        "status_code": 401,
        "event_code": "devpod.workspace.created.v1",
    }
