"""Exécution des règles : gabarits, extraction, comparaison, action.

Aucune I/O ici : l'appel effectif des primitives est injecté (`PrimitiveCaller`),
ce qui rend le moteur intégralement testable sans backend MCP.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import structlog

from ..events.models import AppEvent
from .models import Condition, Rule

_log = structlog.get_logger(__name__)

# (owner_login, service_id, tool_namespacé, args) → résultat JSON décodé (ou texte brut)
PrimitiveCaller = Callable[[str, str, str, dict[str, Any]], Awaitable[Any]]


class AutomationError(Exception):
    """Échec déterministe d'une règle (gabarit, sonde, extraction ou action)."""


def _context(event: AppEvent) -> dict[str, Any]:
    return {
        "workspace": event.workspace or "",
        "actor": event.actor,
        "event": event.type,
        "subject": event.subject,
    }


def render_template(value: str, context: dict[str, Any]) -> str:
    try:
        return value.format_map(context)
    except (KeyError, IndexError) as exc:
        raise AutomationError(f"variable inconnue dans le gabarit {value!r}: {exc}") from exc


def render_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    def render(v: Any) -> Any:
        if isinstance(v, str):
            return render_template(v, context)
        if isinstance(v, dict):
            return {k: render(x) for k, x in v.items()}
        if isinstance(v, list):
            return [render(x) for x in v]
        return v

    return {k: render(v) for k, v in args.items()}


def extract(result: Any, path: str) -> Any:
    """Navigue le résultat JSON selon `path` (segments séparés par des points).

    Sur un dict, une clé absente est une erreur (le contrat de la sonde a changé) ;
    sur une liste, la clé est projetée élément par élément et les éléments qui ne
    la portent pas sont ignorés (listes hétérogènes tolérées).
    """
    if not path:
        return result
    current = result
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise AutomationError(f"chemin {path!r}: clé {segment!r} absente du résultat")
            current = current[segment]
        elif isinstance(current, list):
            current = [e[segment] for e in current if isinstance(e, dict) and segment in e]
        else:
            raise AutomationError(
                f"chemin {path!r}: segment {segment!r} inapplicable à {type(current).__name__}"
            )
    return current


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def check(condition: Condition, result: Any, context: dict[str, Any]) -> bool:
    extracted = extract(result, condition.path)
    value = render_template(condition.value, context)
    if condition.operator == "eq":
        return _as_text(extracted) == value
    if condition.operator == "neq":
        return _as_text(extracted) != value
    if isinstance(extracted, list):
        membership = any(_as_text(e) == value for e in extracted)
    elif isinstance(extracted, dict):
        membership = value in extracted
    else:
        membership = value in _as_text(extracted)
    return membership if condition.operator == "contains" else not membership


async def run_rules(
    rules: Sequence[Rule], event: AppEvent, call_primitive: PrimitiveCaller
) -> list[dict[str, Any]]:
    """Exécute dans l'ordre les règles concernées par l'événement.

    Arrêt à la première règle en échec : les règles suivantes dépendent en
    général de l'état créé par les précédentes — l'erreur remonte au bus qui la
    journalise dans app_event_delivery.
    """
    outcomes: list[dict[str, Any]] = []
    for rule in rules:
        if event.type not in rule.events:
            continue
        outcome = await run_rule(rule, event, call_primitive)
        outcomes.append({"rule": rule.name, "matched": outcome["matched"]})
    return outcomes


async def run_rule(rule: Rule, event: AppEvent, call_primitive: PrimitiveCaller) -> dict[str, Any]:
    """Exécute une règle et retourne sa trace complète.

    Conditions en ET : évaluées dans l'ordre, arrêt au premier faux (les sondes
    suivantes ne sont pas appelées). Aucune condition = vrai. Si la règle
    matche, les actions courent dans l'ordre — la première erreur arrête tout.
    La trace alimente le bouton « Jouer » de l'UI.
    """
    context = _context(event)
    conditions_trace: list[dict[str, Any]] = []
    matched = True
    for idx, cond in enumerate(rule.conditions):
        if cond.service_id is None:
            raise AutomationError(
                f"règle {rule.name!r}: service manquant sur la condition {idx + 1} (supprimé ?)"
            )
        probe_args = render_args(cond.args, context)
        probe_result = await call_primitive(event.actor, cond.service_id, cond.tool, probe_args)
        ok = check(cond, probe_result, context)
        conditions_trace.append(
            {"tool": cond.tool, "args": probe_args, "result": probe_result, "ok": ok}
        )
        if not ok:
            matched = False
            break
    trace: dict[str, Any] = {
        "rule": rule.name,
        "conditions": conditions_trace,
        "matched": matched,
        "actions": [],
    }
    if matched:
        for idx, action in enumerate(rule.actions):
            if action.service_id is None:
                raise AutomationError(
                    f"règle {rule.name!r}: service manquant sur l'action {idx + 1} (supprimé ?)"
                )
            action_args = render_args(action.args, context)
            action_result = await call_primitive(
                event.actor, action.service_id, action.tool, action_args
            )
            trace["actions"].append(
                {"tool": action.tool, "args": action_args, "result": action_result}
            )
    _log.info(
        "automation_rule_evaluated",
        rule=rule.name,
        event_type=event.type,
        actor=event.actor,
        matched=matched,
        actions_ran=len(trace["actions"]),
    )
    return trace
