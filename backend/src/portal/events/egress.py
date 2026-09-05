"""Relais egress des events vers le module workflow : outbox transactionnel.

Contrat de livraison (source de vérité : code du workflow) :
- `POST {workflow_base_url}/events/{source_id}`, corps = enveloppe JSON brute ;
- en-tête `x-signature` = **HMAC-SHA256 hex** des **octets bruts** du corps ;
- succès = **202** (neuf ou dédupliqué). Tout autre code est une erreur de livraison.

Architecture (remplace le best-effort d'origine) : l'écouteur du bus `enqueue_event`
n'INSÈRE que l'enveloppe (mêmes octets à signer et à poster) dans `workflow_event_outbox`,
dans sa transaction — aucun réseau ici. Un worker de fond `outbox_worker_loop` lit les
entrées dues, signe et poste chacune (POST **hors** transaction DB, bug 026), puis
applique retry/backoff. Rien n'est perdu si le workflow est momentanément indisponible.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import httpx
import structlog

from .models import EVENT_TYPES, AppEvent
from .producer import to_envelope

_log = structlog.get_logger(__name__)

_TIMEOUT_S = 10.0

#: Nom stable de l'écouteur de bus qui relaie vers le workflow (clé d'abonnement).
WORKFLOW_PRODUCER = "workflow-producer"

#: Nombre maximal de tentatives de livraison avant abandon définitif (status 'failed').
MAX_ATTEMPTS = 8

#: Rétention des lignes livrées avant purge (heures).
_DELIVERED_RETENTION_HOURS = 24


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
) -> tuple[int, str]:
    """POST l'enveloppe signée vers l'endpoint d'ingestion.

    Retourne `(status, motif)`. Le motif est le diagnostic que l'ingest met
    dans son corps de refus (`reason`, à défaut `detail`) : c'est LUI qui rend
    un échec exploitable — « no_event_context » dit quoi réparer, « HTTP 400 »
    ne dit rien. Vide sur un 202, ou quand le corps n'en porte pas.
    """
    url = f"{base_url.rstrip('/')}/events/{source_id}"
    headers = {"x-signature": signature, "content-type": "application/json"}
    if client is not None:
        resp = await client.post(url, content=raw_body, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as owned:
            resp = await owned.post(url, content=raw_body, headers=headers)
    return resp.status_code, _motif_de_refus(resp)


def _motif_de_refus(resp: httpx.Response) -> str:
    if resp.status_code == httpx.codes.ACCEPTED:
        return ""
    try:
        corps = resp.json()
    except ValueError:
        return ""
    if not isinstance(corps, dict):
        return ""
    return str(corps.get("reason") or corps.get("detail") or "")


async def enqueue_event(event: AppEvent) -> dict[str, Any]:
    """Écouteur du bus : mappe → sérialise → **insère** dans l'outbox (aucun réseau).

    À n'abonner que si `events_producer.enabled` (la fonction suppose la config
    présente). La livraison effective est prise en charge par `outbox_worker_loop`.
    """
    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..db.workflow_outbox import enqueue

    cfg = load_global().events_producer
    envelope = to_envelope(event, source_uri=cfg.source_uri)
    raw = serialize_envelope(envelope)

    async with _get_engine().begin() as conn:
        await enqueue(
            conn,
            event_id=envelope["_eventId"],
            event_code=envelope["_eventCode"],
            raw_body=raw.decode(),
        )
    _log.info(
        "workflow_egress_queued",
        event_code=envelope["_eventCode"],
        event_id=envelope["_eventId"],
    )
    return {"event_code": envelope["_eventCode"], "outbox": "queued"}


def _backoff_seconds(attempts: int) -> float:
    """Backoff exponentiel plafonné à 1h : 30·2^attempts, borné à 3600s."""
    delay: float = 30.0 * 2**attempts
    return delay if delay < 3600.0 else 3600.0


async def deliver_one(
    row: dict[str, Any],
    *,
    base_url: str,
    source_id: str,
    secret: str,
    client: httpx.AsyncClient,
) -> tuple[str, str | None]:
    """Signe + poste UNE ligne d'outbox. Ne touche PAS la DB (pur, testable).

    Retourne :
    - ("delivered", None) si HTTP 202 ;
    - ("failed", message) sinon (l'appelant décide retry vs abandon selon attempts).
    Toute exception réseau est capturée et rendue comme échec (jamais propagée).
    """
    raw = row["raw_body"].encode()
    signature = compute_signature(secret.encode(), raw)
    try:
        status, motif = await post_event(base_url, source_id, raw, signature, client=client)
    except httpx.HTTPError as exc:
        # Message volontairement sans secret ni corps : juste le type et l'URL cible.
        return "failed", f"{type(exc).__name__}: {exc}"
    if status == httpx.codes.ACCEPTED:
        return "delivered", None
    # Le motif de l'ingest (reason/detail) est le diagnostic exploitable — le
    # perdre condamnerait à relire les logs du récepteur pour comprendre.
    return "failed", f"workflow ingestion HTTP {status}" + (f" — {motif}" if motif else "")


async def deliver_due(
    *,
    now: datetime,
    limit: int = 50,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Un passage du worker : charge les lignes dues, poste chacune, applique mark_*.

    - No-op si la feature est désactivée ou la config incomplète.
    - Le secret HMAC est lu via `reveal_system_secret` (connexion courte) ; absent → skip.
    - **Aucun POST dans une transaction DB** (bug 026) : réseau d'abord, mark_* ensuite.
    Retourne un compteur {delivered, retry, failed}.
    """
    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..db.workflow_outbox import claim_due, mark_delivered, mark_failed, mark_retry
    from ..secrets.system import reveal_system_secret

    counts = {"delivered": 0, "retry": 0, "failed": 0}
    cfg = load_global().events_producer
    if not cfg.enabled or not cfg.workflow_base_url or not cfg.source_id:
        return counts

    async with _get_engine().connect() as conn:
        try:
            secret = await reveal_system_secret(cfg.secret_slug, conn)
        except KeyError:
            _log.warning("workflow_egress_secret_missing", slug=cfg.secret_slug)
            return counts

    async with _get_engine().begin() as conn:
        due = await claim_due(conn, now=now, limit=limit)
    if not due:
        return counts

    async def _run(owned: httpx.AsyncClient) -> None:
        for row in due:
            outcome, error = await deliver_one(
                row,
                base_url=cfg.workflow_base_url,
                source_id=cfg.source_id,
                secret=secret,
                client=owned,
            )
            attempts = int(row["attempts"]) + 1
            async with _get_engine().begin() as txn:
                if outcome == "delivered":
                    await mark_delivered(txn, row["id"])
                    counts["delivered"] += 1
                elif attempts >= MAX_ATTEMPTS:
                    await mark_failed(txn, row["id"], error=error or "unknown", attempts=attempts)
                    counts["failed"] += 1
                else:
                    await mark_retry(
                        txn,
                        row["id"],
                        error=error or "unknown",
                        attempts=attempts,
                        next_attempt_at=now + timedelta(seconds=_backoff_seconds(attempts)),
                    )
                    counts["retry"] += 1

    if client is not None:
        await _run(client)
    else:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as owned:
            await _run(owned)
    return counts


async def outbox_worker_loop(interval_s: float = 10.0) -> None:
    """Boucle de fond : livre les entrées dues et purge périodiquement les livrées."""
    from ..db.engine import _get_engine
    from ..db.workflow_outbox import purge_delivered

    await asyncio.sleep(2)  # délai initial — laisse le portail démarrer
    ticks = 0
    while True:
        try:
            now = datetime.now(UTC)
            counts = await deliver_due(now=now)
            if counts["delivered"] or counts["retry"] or counts["failed"]:
                _log.info("workflow_egress_swept", **counts)
            # Purge des livrées ~toutes les ~60 itérations (≈10 min à 10s).
            ticks += 1
            if ticks % 60 == 0:
                cutoff = now - timedelta(hours=_DELIVERED_RETENTION_HOURS)
                async with _get_engine().begin() as conn:
                    purged = await purge_delivered(conn, older_than=cutoff)
                if purged:
                    _log.info("workflow_outbox_purged", count=purged)
        except Exception:
            _log.warning("workflow_outbox_loop_failed", exc_info=True)
        await asyncio.sleep(interval_s)


def reconcile_workflow_producer() -> list[str]:
    """(Ré)aligne l'abonnement du relais workflow sur la config courante.

    Idempotent : désabonne puis réabonne `enqueue_event`. Le relais n'est actif que
    si `enabled` ET une liste blanche non vide (intersectée avec le registre réel).
    Appelé au démarrage (lifespan) et après chaque écriture de config — c'est ce
    qui rend le toggle et la liste blanche effectifs **à chaud**, sans redémarrage.
    Retourne les types effectivement abonnés (vide = relais inactif).
    """
    from ..config.store import load_global
    from .bus import get_bus

    cfg = load_global().events_producer
    bus = get_bus()
    bus.unsubscribe(WORKFLOW_PRODUCER)
    if not cfg.enabled:
        return []
    types = sorted(set(EVENT_TYPES) & set(cfg.events))
    if types:
        bus.subscribe(WORKFLOW_PRODUCER, types, enqueue_event)
    return types
