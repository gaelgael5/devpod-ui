"""Endpoints REST du registre de services — validation + garde profil MCP."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import portal.routes.services as rt

USER = type("U", (), {"login": "admin"})()
CONN = object()


@pytest.fixture
def db(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr(rt.db, "list_services", m.list_services)
    monkeypatch.setattr(rt.db, "create_service", m.create_service)
    monkeypatch.setattr(rt.db, "update_service", m.update_service)
    monkeypatch.setattr(rt.db, "delete_service", m.delete_service)
    return m


@pytest.fixture
def profile_ok(monkeypatch):
    get = AsyncMock(return_value={"id": "p1", "name": "Ops"})
    monkeypatch.setattr(rt.profiles_db, "get_profile", get)
    return get


# ─── validation du body ───────────────────────────────────────────────────────


def test_body_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        rt.ServiceBody(name="  ", url="https://x.example", mcp_profile_id="p1")


def test_body_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError):
        rt.ServiceBody(name="X", url="ftp://x.example", mcp_profile_id="p1")
    with pytest.raises(ValidationError):
        rt.ServiceBody(name="X", url="not a url", mcp_profile_id="p1")


def test_body_ok() -> None:
    body = rt.ServiceBody(name=" Grafana ", url="https://g.example", mcp_profile_id="p1")
    assert body.name == "Grafana"


# ─── routes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_delegates_to_db(db) -> None:
    db.list_services.return_value = [{"id": "s1"}]
    out = await rt.list_services_route(user=USER, conn=CONN)
    assert out == [{"id": "s1"}]


@pytest.mark.asyncio
async def test_create_checks_profile_ownership(db, profile_ok) -> None:
    db.create_service.return_value = "s1"
    body = rt.ServiceBody(name="Grafana", url="https://g.example", mcp_profile_id="p1")
    out = await rt.create_service_route(body, user=USER, conn=CONN)
    assert out == {"id": "s1"}
    profile_ok.assert_awaited_once_with(CONN, "admin", "p1")


@pytest.mark.asyncio
async def test_create_rejects_foreign_profile(db, monkeypatch) -> None:
    monkeypatch.setattr(rt.profiles_db, "get_profile", AsyncMock(return_value=None))
    body = rt.ServiceBody(name="Grafana", url="https://g.example", mcp_profile_id="ghost")
    with pytest.raises(HTTPException) as e:
        await rt.create_service_route(body, user=USER, conn=CONN)
    assert e.value.status_code == 422
    db.create_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_404_when_unknown(db, profile_ok) -> None:
    db.update_service.return_value = False
    body = rt.ServiceBody(name="Grafana", url="https://g.example", mcp_profile_id="p1")
    with pytest.raises(HTTPException) as e:
        await rt.update_service_route("ghost", body, user=USER, conn=CONN)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_404_when_unknown(db) -> None:
    db.delete_service.return_value = False
    with pytest.raises(HTTPException) as e:
        await rt.delete_service_route("ghost", user=USER, conn=CONN)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_ok(db) -> None:
    db.delete_service.return_value = True
    await rt.delete_service_route("s1", user=USER, conn=CONN)  # ne lève pas
