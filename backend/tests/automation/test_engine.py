"""Moteur de règles : gabarits, extraction, opérateurs, exécution ordonnée."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from portal.automation.engine import (
    AutomationError,
    check,
    extract,
    render_args,
    run_rule,
    run_rules,
)
from portal.automation.models import Condition, PrimitiveCall, Rule
from portal.events.models import AppEvent


def _event(**kwargs: Any) -> AppEvent:
    base: dict[str, Any] = {
        "type": "workspace.created",
        "actor": "alice",
        "workspace": "mon-projet",
        "subject": {"ws_id": "alice-mon-projet"},
    }
    base.update(kwargs)
    return AppEvent(**base)


# ─── Gabarits ─────────────────────────────────────────────────────────────────


def test_render_args_substitue_contexte() -> None:
    ctx = {"workspace": "mon-projet", "actor": "alice", "subject": {"ws_id": "alice-mon-projet"}}
    args = {
        "slug": "{workspace}",
        "nested": {"owner": "{actor}", "id": "{subject[ws_id]}"},
        "list": ["{workspace}", 42],
        "untouched": True,
    }
    assert render_args(args, ctx) == {
        "slug": "mon-projet",
        "nested": {"owner": "alice", "id": "alice-mon-projet"},
        "list": ["mon-projet", 42],
        "untouched": True,
    }


def test_render_args_variable_inconnue() -> None:
    with pytest.raises(AutomationError):
        render_args({"x": "{inconnu}"}, {"workspace": "w"})


# ─── Extraction ───────────────────────────────────────────────────────────────


def test_extract_chemin_vide_retourne_tout() -> None:
    assert extract({"a": 1}, "") == {"a": 1}


def test_extract_dict_profond() -> None:
    assert extract({"a": {"b": "x"}}, "a.b") == "x"


def test_extract_liste_projette_la_cle() -> None:
    data = [{"slug": "ws1"}, {"slug": "ws2"}]
    assert extract(data, "slug") == ["ws1", "ws2"]


def test_extract_liste_ignore_les_elements_sans_cle() -> None:
    data = [{"slug": "ws1"}, {"autre": 1}]
    assert extract(data, "slug") == ["ws1"]


def test_extract_cle_absente_dict() -> None:
    with pytest.raises(AutomationError):
        extract({"a": 1}, "b")


# ─── Opérateurs ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("operator", "path", "value", "result", "expected"),
    [
        ("eq", "status", "running", {"status": "running"}, True),
        ("eq", "status", "stopped", {"status": "running"}, False),
        ("neq", "status", "stopped", {"status": "running"}, True),
        ("contains", "slug", "ws1", [{"slug": "ws1"}, {"slug": "ws2"}], True),
        ("contains", "slug", "ws3", [{"slug": "ws1"}], False),
        ("not_contains", "slug", "ws3", [{"slug": "ws1"}], True),
        ("not_contains", "slug", "ws3", [], True),
        ("contains", "", "err", "stderr: error", True),
        ("contains", "", "clé", {"clé": 1}, True),
    ],
)
def test_check_operateurs(
    operator: str, path: str, value: str, result: Any, expected: bool
) -> None:
    cond = Condition(service_id="svc-1", tool="t", path=path, operator=operator, value=value)  # type: ignore[arg-type]
    assert check(cond, result, {"workspace": "w"}) is expected


def test_check_value_est_un_gabarit() -> None:
    cond = Condition(
        service_id="svc-1", tool="t", path="slug", operator="not_contains", value="{workspace}"
    )
    ctx = {"workspace": "mon-projet"}
    assert check(cond, [{"slug": "autre"}], ctx) is True
    assert check(cond, [{"slug": "mon-projet"}], ctx) is False


# ─── Exécution des règles ─────────────────────────────────────────────────────


def _cond(
    tool: str = "docflow__list_workspaces",
    service: str | None = "svc-1",
    path: str = "slug",
    operator: str = "not_contains",
    value: str = "{workspace}",
) -> Condition:
    return Condition(
        service_id=service, tool=tool, args={}, path=path, operator=operator, value=value
    )  # type: ignore[arg-type]


def _action(
    tool: str = "docflow__create_workspace", service: str | None = "svc-1"
) -> PrimitiveCall:
    return PrimitiveCall(
        service_id=service, tool=tool, args={"slug": "{workspace}", "label": "{workspace}"}
    )


def _rule(
    name: str = "r1",
    events: tuple[str, ...] = ("workspace.created",),
    conditions: tuple[Condition, ...] | None = None,
    actions: tuple[PrimitiveCall, ...] | None = None,
) -> Rule:
    return Rule(
        name=name,
        events=events,
        conditions=(_cond(),) if conditions is None else conditions,
        actions=(_action(),) if actions is None else actions,
    )


class _StubCaller:
    """call_primitive de test : réponses programmées, appels enregistrés."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def __call__(self, owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        self.calls.append((owner, service_id, tool, args))
        response = self.responses[tool]
        if isinstance(response, Exception):
            raise response
        return response


async def test_condition_vraie_declenche_l_action() -> None:
    caller = _StubCaller(
        {"docflow__list_workspaces": [], "docflow__create_workspace": {"slug": "mon-projet"}}
    )
    outcomes = await run_rules([_rule()], _event(), caller)
    assert outcomes == [{"rule": "r1", "matched": True}]
    assert caller.calls == [
        ("alice", "svc-1", "docflow__list_workspaces", {}),
        (
            "alice",
            "svc-1",
            "docflow__create_workspace",
            {"slug": "mon-projet", "label": "mon-projet"},
        ),
    ]


async def test_condition_fausse_pas_d_action() -> None:
    caller = _StubCaller({"docflow__list_workspaces": [{"slug": "mon-projet"}]})
    outcomes = await run_rules([_rule()], _event(), caller)
    assert outcomes == [{"rule": "r1", "matched": False}]
    assert [c[2] for c in caller.calls] == ["docflow__list_workspaces"]


async def test_regle_hors_evenement_ignoree() -> None:
    caller = _StubCaller({})
    outcomes = await run_rules([_rule(events=("workspace.deleted",))], _event(), caller)
    assert outcomes == []
    assert caller.calls == []


async def test_echec_de_sonde_arrete_la_sequence() -> None:
    caller = _StubCaller({"docflow__list_workspaces": AutomationError("backend indisponible")})
    with pytest.raises(AutomationError):
        await run_rules([_rule("r1"), _rule("r2")], _event(), caller)
    assert len(caller.calls) == 1


async def test_run_rule_retourne_la_trace_complete() -> None:
    caller = _StubCaller(
        {"docflow__list_workspaces": [], "docflow__create_workspace": {"slug": "mon-projet"}}
    )
    trace = await run_rule(_rule(), _event(), caller)
    assert trace["matched"] is True
    assert trace["conditions"][0]["tool"] == "docflow__list_workspaces"
    assert trace["conditions"][0]["result"] == []
    assert trace["conditions"][0]["ok"] is True
    assert trace["actions"][0]["args"] == {"slug": "mon-projet", "label": "mon-projet"}
    assert trace["actions"][0]["result"] == {"slug": "mon-projet"}


async def test_run_rule_sans_action_si_non_matche() -> None:
    caller = _StubCaller({"docflow__list_workspaces": [{"slug": "mon-projet"}]})
    trace = await run_rule(_rule(), _event(), caller)
    assert trace["matched"] is False
    assert trace["actions"] == []


async def test_et_logique_arret_au_premier_faux() -> None:
    """Deux conditions : la première fausse court-circuite la seconde."""
    caller = _StubCaller({"docflow__list_workspaces": [{"slug": "mon-projet"}]})
    rule = _rule(
        conditions=(
            _cond(),  # not_contains "mon-projet" → faux
            _cond(tool="docflow__list_documents"),  # ne doit jamais être appelée
        )
    )
    trace = await run_rule(rule, _event(), caller)
    assert trace["matched"] is False
    assert len(trace["conditions"]) == 1
    assert [c[2] for c in caller.calls] == ["docflow__list_workspaces"]


async def test_et_logique_toutes_vraies() -> None:
    caller = _StubCaller(
        {
            "docflow__list_workspaces": [],
            "docflow__list_documents": [],
            "docflow__create_workspace": {"slug": "ok"},
        }
    )
    rule = _rule(conditions=(_cond(), _cond(tool="docflow__list_documents")))
    trace = await run_rule(rule, _event(), caller)
    assert trace["matched"] is True
    assert [c["ok"] for c in trace["conditions"]] == [True, True]


async def test_sans_condition_les_actions_courent_toujours() -> None:
    caller = _StubCaller({"docflow__create_workspace": {"slug": "ok"}})
    trace = await run_rule(_rule(conditions=()), _event(), caller)
    assert trace["matched"] is True
    assert len(trace["actions"]) == 1


async def test_actions_multiples_dans_l_ordre() -> None:
    caller = _StubCaller(
        {
            "docflow__list_workspaces": [],
            "docflow__create_workspace": {"slug": "ok"},
            "docflow__create_block": {"slug": "planner"},
        }
    )
    rule = _rule(actions=(_action(), _action(tool="docflow__create_block")))
    trace = await run_rule(rule, _event(), caller)
    assert [a["tool"] for a in trace["actions"]] == [
        "docflow__create_workspace",
        "docflow__create_block",
    ]


async def test_erreur_d_action_arrete_les_suivantes() -> None:
    caller = _StubCaller(
        {
            "docflow__list_workspaces": [],
            "docflow__create_workspace": AutomationError("409"),
            "docflow__create_block": {"slug": "planner"},
        }
    )
    rule = _rule(actions=(_action(), _action(tool="docflow__create_block")))
    with pytest.raises(AutomationError):
        await run_rule(rule, _event(), caller)
    assert "docflow__create_block" not in [c[2] for c in caller.calls]


async def test_service_condition_manquant_est_une_erreur() -> None:
    """Service supprimé : la règle est inopérante et le dit."""
    caller = _StubCaller({})
    with pytest.raises(AutomationError, match="condition 1"):
        await run_rule(_rule(conditions=(_cond(service=None),)), _event(), caller)
    assert caller.calls == []


async def test_service_action_manquant_est_une_erreur() -> None:
    caller = _StubCaller({"docflow__list_workspaces": []})
    with pytest.raises(AutomationError, match="action 1"):
        await run_rule(_rule(actions=(_action(service=None),)), _event(), caller)


def test_au_moins_une_action_requise() -> None:
    with pytest.raises(ValidationError):
        _rule(actions=())
