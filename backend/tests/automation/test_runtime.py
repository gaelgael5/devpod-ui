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


async def test_pas_de_chaine_si_non_matche(caller: list[str], rules_db: AsyncMock) -> None:
    row = _row(
        next_rule_id="r2",
        conditions=[{**_COND, "operator": "contains"}],  # [] contains → faux
    )
    traces = await run_rule_chain(row, _event(), "alice")
    assert len(traces) == 1
    rules_db.assert_not_awaited()


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
