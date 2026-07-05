"""Exécution des règles utilisateur stockées en base.

Conversion ligne user_rules → Rule moteur, écouteur générique branché sur tous
les types d'événements : à chaque événement, les règles enabled de l'acteur qui
visent ce type sont déroulées dans l'ordre de création.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..db.engine import _get_engine
from ..db.user_rules import list_enabled_rules_for_event
from ..events.bus import EventBus
from ..events.models import EVENT_TYPES, AppEvent
from .engine import run_rule
from .models import Condition, PrimitiveCall, Rule
from .service_exec import call_service_primitive

_log = structlog.get_logger(__name__)

LISTENER_NAME = "user-rules"


def rule_row_to_engine(row: dict[str, Any]) -> Rule:
    return Rule(
        name=row["name"],
        events=(row["event_type"],),
        probe=PrimitiveCall(
            service_id=row["probe_service_id"],
            tool=row["probe_tool"],
            args=row["probe_args"],
        ),
        condition=Condition(
            path=row["condition_path"],
            operator=row["condition_operator"],
            value=row["condition_value"],
        ),
        action=PrimitiveCall(
            service_id=row["action_service_id"],
            tool=row["action_tool"],
            args=row["action_args"],
        ),
    )


async def run_user_rules(event: AppEvent) -> None:
    """Déroule les règles de l'acteur pour cet événement. Arrêt à la première erreur.

    L'erreur remonte au bus, qui la journalise dans app_event_delivery — visible
    dans l'onglet Événements, rejouable une fois la règle corrigée.
    """
    async with _get_engine().connect() as conn:
        rows = await list_enabled_rules_for_event(conn, event.actor, event.type)
    if not rows:
        return
    for row in rows:
        trace = await run_rule(rule_row_to_engine(row), event, call_service_primitive)
        _log.info(
            "user_rule_done",
            rule_id=row["id"],
            rule=row["name"],
            event_type=event.type,
            matched=trace["matched"],
            action_ran=trace["action"] is not None,
        )


def register_automation(bus: EventBus) -> None:
    bus.subscribe(LISTENER_NAME, sorted(EVENT_TYPES), run_user_rules)
