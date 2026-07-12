"""Egress signé vers le workflow : signature, sérialisation, POST.

L'écouteur du bus (`enqueue_event`) et la logique de livraison/retry sont testés
dans `test_outbox.py`. Ce fichier couvre les primitives pures conservées.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

import httpx

from portal.events.egress import (
    compute_signature,
    post_event,
    serialize_envelope,
)


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
