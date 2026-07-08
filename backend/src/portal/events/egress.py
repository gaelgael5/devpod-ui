"""Relais egress des events vers le module workflow : signature HMAC + POST ingestion.

Contrat (source de vérité : code du workflow) :
- `POST {workflow_base_url}/events/{source_id}`, corps = enveloppe JSON brute ;
- en-tête `x-signature` = **HMAC-SHA256 hex** des **octets bruts** du corps ;
- succès = **202** (neuf ou dédupliqué). Tout autre code est une erreur de livraison.

Livraison **best-effort** : branché comme écouteur du bus, qui isole et journalise
déjà chaque livraison (app_event_delivery). L'écouteur lève sur échec → le bus trace
l'erreur ; aucune file d'attente ni retry différé (choix assumé, aligné sur le bus).
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

import httpx
import structlog

from .models import AppEvent
from .producer import to_envelope

_log = structlog.get_logger(__name__)

_TIMEOUT_S = 10.0


class EgressError(Exception):
    """Échec de livraison vers le workflow. `delivery_detail` est journalisé par le bus."""

    def __init__(self, message: str, *, delivery_detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.delivery_detail = delivery_detail


def compute_signature(secret: bytes, raw_body: bytes) -> str:
    """HMAC-SHA256 hex des octets bruts du corps (identique à la vérif workflow)."""
    return hmac.new(secret, raw_body, sha256).hexdigest()


def serialize_envelope(envelope: dict[str, Any]) -> bytes:
    """Sérialise l'enveloppe en octets **stables** : ce sont ces octets qui sont signés
    ET postés (jamais de re-sérialisation entre signature et envoi — sinon 401)."""
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode()


async def post_event(
    base_url: str,
    source_id: str,
    raw_body: bytes,
    signature: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> int:
    """POST l'enveloppe signée vers l'endpoint d'ingestion. Retourne le status HTTP."""
    url = f"{base_url.rstrip('/')}/events/{source_id}"
    headers = {"x-signature": signature, "content-type": "application/json"}
    if client is not None:
        resp = await client.post(url, content=raw_body, headers=headers)
        return resp.status_code
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as owned:
        resp = await owned.post(url, content=raw_body, headers=headers)
        return resp.status_code


async def forward_to_workflow(event: AppEvent) -> dict[str, Any]:
    """Écouteur du bus : mappe → signe → poste. Lève `EgressError` sur échec (best-effort).

    À n'abonner que si `events_producer.enabled` : la fonction suppose la config valide.
    """
    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..secrets.system import reveal_system_secret

    cfg = load_global().events_producer
    envelope = to_envelope(event, source_uri=cfg.source_uri)
    raw = serialize_envelope(envelope)

    async with _get_engine().connect() as conn:
        secret = await reveal_system_secret(cfg.secret_slug, conn)
    signature = compute_signature(secret.encode(), raw)

    status = await post_event(cfg.workflow_base_url, cfg.source_id, raw, signature)
    detail = {"status_code": status, "event_code": envelope["_eventCode"]}
    if status != httpx.codes.ACCEPTED:
        _log.warning(
            "workflow_egress_rejected",
            event_code=envelope["_eventCode"],
            event_id=envelope["_eventId"],
            status_code=status,
        )
        raise EgressError(f"workflow ingestion HTTP {status}", delivery_detail=detail)
    _log.info(
        "workflow_egress_delivered",
        event_code=envelope["_eventCode"],
        event_id=envelope["_eventId"],
    )
    return detail
