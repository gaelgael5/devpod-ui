"""Endpoints REST du bloc Rules — validation, garde services, test avec trace."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import portal.routes.user_rules as rt

USER = type("U", (), {"login": "alice"})()
CONN = object()


def _body(**overrides: Any) -> rt.RuleBody:
    base: dict[str, Any] = {
        "name": "docflow workspace",
        "event_type": "workspace.created",
        "probe": {"service_id": "svc-1", "tool": "docflow__list_workspaces", "args": {}},
        "condition": {"path": "slug", "operator": "not_contains", "value": "{workspace}"},
        "action": {
            "service_id": "svc-1",
            "tool": "docflow__create_workspace",
            "args": {"slug": "{workspace}", "label": "{workspace}"},
        },
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
        "probe_service_id": "svc-1",
        "probe_tool": "docflow__list_workspaces",
        "probe_args": {},
        "condition_path": "slug",
        "condition_operator": "not_contains",
        "condition_value": "{workspace}",
        "action_service_id": "svc-1",
        "action_tool": "docflow__create_workspace",
        "action_args": {"slug": "{workspace}", "label": "{workspace}"},
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
        _body(condition={"path": "", "operator": "regex", "value": "x"})


def test_body_rejette_outil_vide() -> None:
    with pytest.raises(ValidationError):
        _body(probe={"service_id": "svc-1", "tool": "  ", "args": {}})


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_verifie_les_services(db: AsyncMock, services_ok: AsyncMock) -> None:
    db.create_rule.return_value = "r1"
    out = await rt.create_rule_route(_body(), user=USER, conn=CONN)
    assert out == {"id": "r1"}
    services_ok.assert_awaited_with(CONN, "alice", "svc-1")
    fields = db.create_rule.await_args.kwargs
    assert fields["event_type"] == "workspace.created"
    assert fields["probe_tool"] == "docflow__list_workspaces"


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
async def test_update_404_si_inconnue(db: AsyncMock, services_ok: AsyncMock) -> None:
    db.update_rule.return_value = False
    with pytest.raises(HTTPException) as e:
        await rt.update_rule_route("ghost", _body(), user=USER, conn=CONN)
    assert e.value.status_code == 404


# ─── test / jouer ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jouer_retourne_la_trace(db: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    db.get_rule.return_value = _row()
    calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def fake_caller(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        calls.append((owner, service_id, tool, args))
        return [] if tool == "docflow__list_workspaces" else {"slug": "mon-projet"}

    monkeypatch.setattr(rt, "call_service_primitive", fake_caller)
    out = await rt.test_rule_route(
        "r1", rt.RuleTestBody(workspace="mon-projet"), user=USER, conn=CONN
    )
    assert out["ok"] is True
    assert out["matched"] is True
    assert out["action"]["args"] == {"slug": "mon-projet", "label": "mon-projet"}
    assert [c[2] for c in calls] == ["docflow__list_workspaces", "docflow__create_workspace"]


@pytest.mark.asyncio
async def test_jouer_erreur_metier_en_clair(db: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    db.get_rule.return_value = _row(probe_service_id=None)
    out = await rt.test_rule_route("r1", rt.RuleTestBody(), user=USER, conn=CONN)
    assert out["ok"] is False
    assert "sonde" in out["error"]


@pytest.mark.asyncio
async def test_jouer_404_si_inconnue(db: AsyncMock) -> None:
    db.get_rule.return_value = None
    with pytest.raises(HTTPException) as e:
        await rt.test_rule_route("ghost", rt.RuleTestBody(), user=USER, conn=CONN)
    assert e.value.status_code == 404
