"""Bus d'événements in-process : journal d'abord, dispatch asynchrone.

Sémantique : at-least-once, écouteurs idempotents par construction (règles
« ensure »). `emit()` ne lève JAMAIS vers l'appelant — ni un journal en panne
ni un écouteur qui plante ne doivent faire échouer l'opération métier émettrice.
Chaque livraison est tracée dans app_event_delivery (ok/error).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import structlog

from .models import EVENT_TYPES, AppEvent

_log = structlog.get_logger(__name__)

Handler = Callable[[AppEvent], Awaitable[None]]


async def _persist_event(event: AppEvent) -> None:
    from ..db.app_events import insert_event
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await insert_event(
            conn,
            event_id=event.event_id,
            event_type=event.type,
            actor=event.actor,
            workspace=event.workspace,
            subject=event.subject,
            correlation_id=event.correlation_id,
            occurred_at=event.occurred_at,
        )


async def _persist_delivery(event_id: str, listener: str, status: str, error: str | None) -> None:
    from ..db.app_events import insert_delivery
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await insert_delivery(
            conn, event_id=event_id, listener=listener, status=status, error=error
        )


@dataclass(frozen=True)
class _Subscription:
    name: str
    event_types: frozenset[str]
    handler: Handler


class EventBus:
    def __init__(self) -> None:
        self._subs: list[_Subscription] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def subscribe(self, name: str, event_types: Iterable[str], handler: Handler) -> None:
        types = frozenset(event_types)
        unknown = types - EVENT_TYPES
        if unknown:
            raise ValueError(f"types d'événements inconnus: {sorted(unknown)}")
        if any(s.name == name for s in self._subs):
            raise ValueError(f"écouteur déjà enregistré: {name!r}")
        self._subs.append(_Subscription(name=name, event_types=types, handler=handler))

    async def emit(self, event: AppEvent) -> None:
        """Journalise puis planifie la livraison en tâche de fond. Ne lève jamais."""
        try:
            await _persist_event(event)
        except Exception:
            _log.error(
                "event_journal_failed",
                event_type=event.type,
                event_id=event.event_id,
                exc_info=True,
            )
        task = asyncio.create_task(self._dispatch(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(self, event: AppEvent) -> None:
        for sub in [s for s in self._subs if event.type in s.event_types]:
            status, error = "ok", None
            try:
                await sub.handler(event)
            except Exception as exc:
                status, error = "error", f"{type(exc).__name__}: {exc}"
                _log.error(
                    "event_listener_failed",
                    listener=sub.name,
                    event_type=event.type,
                    event_id=event.event_id,
                    error=error,
                )
            try:
                await _persist_delivery(event.event_id, sub.name, status, error)
            except Exception:
                _log.error(
                    "event_delivery_journal_failed",
                    listener=sub.name,
                    event_id=event.event_id,
                    exc_info=True,
                )

    async def redeliver(self, event: AppEvent) -> None:
        """Rejoue les livraisons d'un événement déjà journalisé (replay).

        L'événement n'est PAS réinséré dans app_event ; les nouvelles livraisons
        s'ajoutent à l'historique dans app_event_delivery. Sûr par construction :
        les écouteurs sont des règles « ensure » idempotentes.
        """
        task = asyncio.create_task(self._dispatch(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Attend la fin des livraisons en cours (tests, arrêt propre)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Annule les livraisons en attente et vide les abonnements (shutdown)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._subs.clear()


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_bus() -> None:
    """Oublie le singleton — indispensable entre deux apps successives (tests)."""
    global _bus
    _bus = None


async def emit_event(
    event_type: str,
    *,
    actor: str,
    workspace: str | None = None,
    subject: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Construit et émet un événement via le bus singleton. Ne lève jamais."""
    try:
        event = AppEvent(
            type=event_type,
            actor=actor,
            workspace=workspace,
            subject=subject or {},
            correlation_id=correlation_id,
        )
    except Exception:
        _log.error("event_invalid", event_type=event_type, exc_info=True)
        return
    await get_bus().emit(event)
