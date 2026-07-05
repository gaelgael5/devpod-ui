"""Endpoints REST du bloc Rules v2 — validation, gardes services/chaîne, test."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import portal.routes.user_rules as rt

USER = type("U", (), {"login": "alice"})()
CONN = object()

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


def _body(**overrides: Any) -> rt.RuleBody:
    base: dict[str, Any] = {
        "name": "docflow workspace",
        "event_type": "workspace.created",
        "conditions": [_COND],
        "actions": [_ACTION],
    }
    base.update(overrides)
    return rt.RuleBody(**base)


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


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(rt.db, "list_rules", m.list_rules)
    monkeypatch.setattr(rt.db, "create_rule", m.create_rule)
    monkeypatch.setattr(rt.db, "update_rule", m.update_rule)
    monkeypatch.setattr(rt.db, "delete_rule", m.delete_rule)
    monkeypatch.setattr(rt.db, "get_rule", m.get_rule)
    return m


@pytest.fixture
def services_ok(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    get = AsyncMock(return_value={"id": "svc-1", "name": "Docflow", "mcp_profile_id": "p1"})
    monkeypatch.setattr(rt.services_db, "get_service", get)
    return get


# ─── validation du body ───────────────────────────────────────────────────────


def test_body_rejette_event_inconnu() -> None:
    with pytest.raises(ValidationError):
        _body(event_type="workspace.exploded")


def test_body_rejette_operateur_inconnu() -> None:
    with pytest.raises(ValidationError):
        _body(conditions=[{**_COND, "operator": "regex"}])


def test_body_rejette_sans_action() -> None:
    with pytest.raises(ValidationError):
        _body(actions=[])


def test_body_sans_condition_ok() -> None:
    assert _body(conditions=[]).conditions == []


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_verifie_les_services(db: AsyncMock, services_ok: AsyncMock) -> None:
    db.create_rule.return_value = "r1"
    out = await rt.create_rule_route(_body(), user=USER, conn=CONN)
    assert out == {"id": "r1"}
    services_ok.assert_awaited_with(CONN, "alice", "svc-1")
    fields = db.create_rule.await_args.kwargs
    assert fields["conditions"][0]["tool"] == "docflow__list_workspaces"
    assert fields["actions"][0]["tool"] == "docflow__create_workspace"


@pytest.mark.asyncio
async def test_create_rejette_service_etranger(
    db: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt.services_db, "get_service", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as e:
        await rt.create_rule_route(_body(), user=USER, conn=CONN)
    assert e.value.status_code == 422
    db.create_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejette_chaine_inconnue(db: AsyncMock, services_ok: AsyncMock) -> None:
    db.get_rule.return_value = None
    with pytest.raises(HTTPException) as e:
        await rt.create_rule_route(_body(next_rule_id="ghost"), user=USER, conn=CONN)
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_update_rejette_auto_chainage(db: AsyncMock, services_ok: AsyncMock) -> None:
    with pytest.raises(HTTPException) as e:
        await rt.update_rule_route("r1", _body(next_rule_id="r1"), user=USER, conn=CONN)
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_update_404_si_inconnue(db: AsyncMock, services_ok: AsyncMock) -> None:
    db.update_rule.return_value = False
    with pytest.raises(HTTPException) as e:
        await rt.update_rule_route("ghost", _body(), user=USER, conn=CONN)
    assert e.value.status_code == 404


# ─── test / jouer ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jouer_retourne_les_traces(db: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    db.get_rule.return_value = _row()

    async def fake_chain(row: dict[str, Any], event: Any, owner: str) -> list[dict[str, Any]]:
        assert event.workspace == "mon-projet"
        return [{"rule": row["name"], "conditions": [], "matched": True, "actions": []}]

    monkeypatch.setattr(rt, "run_rule_chain", fake_chain)
    out = await rt.test_rule_route(
        "r1", rt.RuleTestBody(workspace="mon-projet"), user=USER, conn=CONN
    )
    assert out["ok"] is True
    assert out["traces"][0]["rule"] == "docflow workspace"


@pytest.mark.asyncio
async def test_jouer_erreur_metier_en_clair(db: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    db.get_rule.return_value = _row(conditions=[{**_COND, "service_id": None}])
    out = await rt.test_rule_route("r1", rt.RuleTestBody(), user=USER, conn=CONN)
    assert out["ok"] is False
    assert "condition" in out["error"]


@pytest.mark.asyncio
async def test_jouer_404_si_inconnue(db: AsyncMock) -> None:
    db.get_rule.return_value = None
    with pytest.raises(HTTPException) as e:
        await rt.test_rule_route("ghost", rt.RuleTestBody(), user=USER, conn=CONN)
    assert e.value.status_code == 404
