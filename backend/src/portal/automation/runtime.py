"""Exécution des règles utilisateur stockées en base, avec enchaînement.

Conversion ligne user_rules → Rule moteur, écouteur générique branché sur tous
les types d'événements. Une règle dont les actions ont couru peut enchaîner sur
une autre règle (next_rule_id) : la suivante est jouée avec le même contexte
d'événement, ses propres conditions décident. Garde-fous : profondeur maximale
et détection de cycle.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..db.engine import _get_engine
from ..db.user_rules import get_rule, list_enabled_rules_for_event
from ..events.bus import EventBus
from ..events.models import EVENT_TYPES, AppEvent
from .engine import AutomationError, run_rule
from .models import Condition, PrimitiveCall, Rule
from .service_exec import call_service_primitive

_log = structlog.get_logger(__name__)

LISTENER_NAME = "user-rules"
MAX_CHAIN_DEPTH = 5


def rule_row_to_engine(row: dict[str, Any]) -> Rule:
    return Rule(
        name=row["name"],
        events=(row["event_type"],),
        conditions=tuple(Condition(**c) for c in row["conditions"]),
        actions=tuple(PrimitiveCall(**a) for a in row["actions"]),
        next_rule=row["next_rule_id"],
    )


async def run_rule_chain(
    row: dict[str, Any], event: AppEvent, owner_login: str
) -> list[dict[str, Any]]:
    """Joue une règle puis sa règle chaînée (ordre de lancement), etc.

    Retourne les traces de toute la chaîne (une par règle jouée). L'enchaînement
    suit next_rule_id que les conditions aient été vraies ou non ; une règle
    chaînée désactivée, déjà visitée (cycle) ou au-delà de la profondeur max
    arrête l'enchaînement — signalé dans la trace, jamais silencieux.
    """
    traces: list[dict[str, Any]] = []
    visited: set[str] = set()
    current: dict[str, Any] | None = row
    while current is not None:
        visited.add(current["id"])
        trace = await run_rule(rule_row_to_engine(current), event, call_service_primitive)
        traces.append(trace)
        next_id = current["next_rule_id"]
        # L'enchaînement est un ORDRE DE LANCEMENT : la règle suivante tourne
        # même si les conditions de celle-ci étaient fausses (choix utilisateur).
        if not next_id:
            break
        if next_id in visited:
            trace["chain_stopped"] = "cycle détecté"
            _log.warning("user_rule_chain_cycle", rule_id=current["id"], next_rule_id=next_id)
            break
        if len(visited) >= MAX_CHAIN_DEPTH:
            trace["chain_stopped"] = f"profondeur maximale atteinte ({MAX_CHAIN_DEPTH})"
            _log.warning("user_rule_chain_too_deep", rule_id=current["id"])
            break
        async with _get_engine().connect() as conn:
            nxt = await get_rule(conn, owner_login, next_id)
        if nxt is None:
            trace["chain_stopped"] = "règle chaînée introuvable"
            break
        if not nxt["enabled"]:
            trace["chain_stopped"] = "règle chaînée désactivée"
            break
        current = nxt
    return traces


async def run_user_rules(event: AppEvent) -> list[dict[str, Any]] | None:
    """Déroule les règles de l'acteur pour cet événement.

    Chaque règle racine est indépendante : une erreur n'empêche pas les
    suivantes de courir. Le détail par règle (verdict, actions, erreur) est
    retourné au bus qui le journalise dans app_event_delivery — visible dans
    l'onglet Événements. S'il y a au moins une erreur, l'exception finale porte
    ce détail (delivery_detail) et la livraison passe en erreur.
    """
    async with _get_engine().connect() as conn:
        rows = await list_enabled_rules_for_event(conn, event.actor, event.type)
    if not rows:
        return None
    detail: list[dict[str, Any]] = []
    failed: list[str] = []
    for row in rows:
        try:
            traces = await run_rule_chain(row, event, event.actor)
        except Exception as exc:
            detail.append(
                {
                    "rule": row["name"],
                    "rule_id": row["id"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            failed.append(row["name"])
            _log.error(
                "user_rule_failed",
                rule_id=row["id"],
                rule=row["name"],
                event_type=event.type,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        for trace in traces:
            entry: dict[str, Any] = {
                "rule": trace["rule"],
                "matched": trace["matched"],
                "actions_ran": len(trace["actions"]),
            }
            if trace.get("chain_stopped"):
                entry["chain_stopped"] = trace["chain_stopped"]
            detail.append(entry)
        _log.info(
            "user_rule_done",
            rule_id=row["id"],
            rule=row["name"],
            event_type=event.type,
            matched=traces[0]["matched"],
            chain_length=len(traces),
        )
    if failed:
        exc_out = AutomationError(f"règle(s) en échec: {', '.join(failed)}")
        exc_out.delivery_detail = detail
        raise exc_out
    return detail


def register_automation(bus: EventBus) -> None:
    bus.subscribe(LISTENER_NAME, sorted(EVENT_TYPES), run_user_rules)


__all__ = [
    "AutomationError",
    "LISTENER_NAME",
    "MAX_CHAIN_DEPTH",
    "register_automation",
    "rule_row_to_engine",
    "run_rule_chain",
    "run_user_rules",
]
