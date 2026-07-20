"""Bus d'événements in-process : dispatch asynchrone vers les abonnés.

Sémantique : at-least-once, écouteurs idempotents par construction. `emit()` ne
lève JAMAIS vers l'appelant — un écouteur qui plante ne doit pas faire échouer
l'opération métier émettrice. Le seul abonné aujourd'hui est le producteur
workflow (`events/egress.enqueue_event`), qui persiste dans son propre outbox.
Le journal local (tables app_event*) a été retiré avec les onglets Rules/Events.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import structlog

from .models import EVENT_TYPES, AppEvent

_log = structlog.get_logger(__name__)

# Un handler peut retourner un détail structuré (JSON-sérialisable) — logué en cas d'échec.
Handler = Callable[[AppEvent], Awaitable[Any]]


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

    def unsubscribe(self, name: str) -> bool:
        """Retire un écouteur par nom. Idempotent : retourne True si un abonnement a été retiré."""
        before = len(self._subs)
        self._subs = [s for s in self._subs if s.name != name]
        return len(self._subs) != before

    def has_subscriber(self, name: str) -> bool:
        return any(s.name == name for s in self._subs)

    async def emit(self, event: AppEvent) -> None:
        """Planifie la livraison aux abonnés en tâche de fond. Ne lève jamais."""
        task = asyncio.create_task(self._dispatch(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(self, event: AppEvent) -> None:
        for sub in [s for s in self._subs if event.type in s.event_types]:
            try:
                await sub.handler(event)
            except Exception as exc:
                _log.error(
                    "event_listener_failed",
                    listener=sub.name,
                    event_type=event.type,
                    event_id=event.event_id,
                    error=f"{type(exc).__name__}: {exc}",
                )

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
