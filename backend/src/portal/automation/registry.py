"""Enregistrement des écouteurs d'automatisation sur le bus d'événements."""

from __future__ import annotations

from ..events.bus import EventBus
from ..events.models import AppEvent
from .docflow_rules import DOCFLOW_BOOTSTRAP_RULES
from .engine import run_rules
from .mcp_exec import call_user_primitive


def register_automation(bus: EventBus) -> None:
    events = sorted({e for rule in DOCFLOW_BOOTSTRAP_RULES for e in rule.events})

    async def _docflow_bootstrap(event: AppEvent) -> None:
        await run_rules(DOCFLOW_BOOTSTRAP_RULES, event, call_user_primitive)

    bus.subscribe("docflow-bootstrap", events, _docflow_bootstrap)
