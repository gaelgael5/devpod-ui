"""Runtime des règles utilisateur : conversion ligne DB, enchaînement, garde-fous."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import portal.automation.runtime as runtime
from portal.automation.runtime import rule_row_to_engine, run_rule_chain
from portal.events.models import AppEvent

_COND = {
    "service_id": "svc-1",
    "tool": "docflow__list_workspaces",
    "args": {},
    "path": "slug",
    "operator": "not_contains",
    "value": "{workspace}",
}
_ACTION = {
    "service_id": "svc-1",
    "tool": "docflow__create_workspace",
    "args": {"slug": "{workspace}", "label": "{workspace}"},
}


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "r1",
        "owner_login": "alice",
        "name": "docflow workspace",
        "enabled": True,
        "event_type": "workspace.created",
        "conditions": [_COND],
        "actions": [_ACTION],
        "next_rule_id": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


def _event() -> AppEvent:
    return AppEvent(type="workspace.created", actor="alice", workspace="mon-projet")


# ─── Conversion ───────────────────────────────────────────────────────────────


def test_conversion_complete() -> None:
    rule = rule_row_to_engine(_row())
    assert rule.events == ("workspace.created",)
    assert rule.conditions[0].tool == "docflow__list_workspaces"
    assert rule.conditions[0].operator == "not_contains"
    assert rule.actions[0].args == {"slug": "{workspace}", "label": "{workspace}"}


def test_service_supprime_donne_service_id_none() -> None:
    rule = rule_row_to_engine(_row(conditions=[{**_COND, "service_id": None}]))
    assert rule.conditions[0].service_id is None


def test_event_type_inconnu_rejete() -> None:
    with pytest.raises(ValidationError):
        rule_row_to_engine(_row(event_type="workspace.exploded"))


def test_operateur_inconnu_rejete() -> None:
    with pytest.raises(ValidationError):
        rule_row_to_engine(_row(conditions=[{**_COND, "operator": "regex"}]))


# ─── Enchaînement ─────────────────────────────────────────────────────────────


@pytest.fixture
def caller(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """call_service_primitive stub : sondes vides (conditions vraies), actions ok."""
    calls: list[str] = []

    async def fake(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        calls.append(tool)
        return [] if "list" in tool else {"ok": True}

    monkeypatch.setattr(runtime, "call_service_primitive", fake)
    return calls


@pytest.fixture
def rules_db(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(runtime, "get_rule", m)

    class _Conn:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(runtime, "_get_engine", lambda: type("E", (), {"connect": _Conn})())
    return m


async def test_chaine_deux_regles(caller: list[str], rules_db: AsyncMock) -> None:
    r2 = _row(id="r2", name="règle 2", actions=[{**_ACTION, "tool": "docflow__create_block"}])
    rules_db.return_value = r2
    traces = await run_rule_chain(_row(next_rule_id="r2"), _event(), "alice")
    assert [t["rule"] for t in traces] == ["docflow workspace", "règle 2"]
    assert "docflow__create_block" in caller


async def test_chaine_meme_si_non_matche(caller: list[str], rules_db: AsyncMock) -> None:
    """L'enchaînement est un ordre de lancement : il suit même conditions fausses."""
    rules_db.return_value = _row(id="r2", name="règle 2")
    row = _row(
        next_rule_id="r2",
        conditions=[{**_COND, "operator": "contains"}],  # [] contains → faux
    )
    traces = await run_rule_chain(row, _event(), "alice")
    assert len(traces) == 2
    assert traces[0]["matched"] is False
    assert traces[1]["rule"] == "règle 2"


async def test_cycle_detecte(caller: list[str], rules_db: AsyncMock) -> None:
    """r1 → r2 → r1 : le cycle s'arrête, signalé dans la trace."""
    r2 = _row(id="r2", name="règle 2", next_rule_id="r1")
    rules_db.return_value = r2
    traces = await run_rule_chain(_row(next_rule_id="r2"), _event(), "alice")
    assert len(traces) == 2
    assert "cycle" in traces[-1]["chain_stopped"]


async def test_chaine_desactivee_arretee(caller: list[str], rules_db: AsyncMock) -> None:
    rules_db.return_value = _row(id="r2", enabled=False)
    traces = await run_rule_chain(_row(next_rule_id="r2"), _event(), "alice")
    assert len(traces) == 1
    assert "désactivée" in traces[0]["chain_stopped"]


# ─── run_user_rules : détail journalisé + indépendance des règles racines ─────


@pytest.fixture
def rules_for_event(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(runtime, "list_enabled_rules_for_event", m)

    class _Conn:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(runtime, "_get_engine", lambda: type("E", (), {"connect": _Conn})())
    return m


async def test_run_user_rules_retourne_le_detail(
    caller: list[str], rules_for_event: AsyncMock
) -> None:
    rules_for_event.return_value = [_row()]
    detail = await runtime.run_user_rules(_event())
    assert detail == [{"rule": "docflow workspace", "matched": True, "actions_ran": 1}]


async def test_run_user_rules_continue_apres_une_erreur(
    rules_for_event: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les règles racines sont indépendantes ; l'exception finale porte le détail."""
    r_ko = _row(id="r-ko", name="cassée", conditions=[{**_COND, "service_id": None}])
    r_ok = _row(id="r-ok", name="saine")
    rules_for_event.return_value = [r_ko, r_ok]

    async def fake_caller(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        return [] if "list" in tool else {"ok": True}

    monkeypatch.setattr(runtime, "call_service_primitive", fake_caller)
    with pytest.raises(runtime.AutomationError) as e:
        await runtime.run_user_rules(_event())
    detail = e.value.delivery_detail
    assert detail is not None
    assert detail[0]["rule"] == "cassée" and "error" in detail[0]
    assert detail[1] == {"rule": "saine", "matched": True, "actions_ran": 1}
