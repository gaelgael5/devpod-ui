"""Endpoints service bastion (connecteur Termix par automates) : auth + statuts honnêtes.

Auth réelle testée (rejet sans identité) ; l'orchestration `bastion/provision` est
monkeypatchée — le contrat testé ici est celui de la traduction HTTP :
nominal 200, config incomplète 409, entrée invalide 422, échec Termix 502.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin_or_api_key
from portal.bastion.provision import BastionNotConfiguredError
from portal.routes import service_bastion
from portal.routes.service_bastion import router as service_bastion_router


class _Acm:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *a: object) -> bool:
        return False


class _FakeEngine:
    def connect(self) -> _Acm:
        return _Acm()

    def begin(self) -> _Acm:
        return _Acm()


def _app(monkeypatch: pytest.MonkeyPatch, *, authenticated: bool = True) -> TestClient:
    async def _audit(*a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(service_bastion, "audit_record", _audit)
    monkeypatch.setattr(service_bastion, "_get_engine", lambda: _FakeEngine())

    app = FastAPI()
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(service_bastion_router, prefix="/admin/service")
    if authenticated:
        app.dependency_overrides[require_admin_or_api_key] = lambda: UserInfo(
            login="__api__", roles=["admin"]
        )
    return TestClient(app)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _app(monkeypatch)


def test_provision_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch, authenticated=False)
    resp = client.post(
        "/admin/service/bastion/provision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code in (401, 403)


def test_provision_nominal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _provision(login: str, ws_id: str) -> dict[str, Any]:
        assert (login, ws_id) == ("alice", "alice-proj")
        return {"ws_id": ws_id, "host_id": 7, "cred_id": 3, "created": True}

    monkeypatch.setattr(service_bastion, "provision_workspace", _provision)
    resp = client.post(
        "/admin/service/bastion/provision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ws_id": "alice-proj", "host_id": 7, "cred_id": 3, "created": True}


def test_provision_409_when_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _provision(login: str, ws_id: str) -> dict[str, Any]:
        raise BastionNotConfiguredError("bastion non configuré")

    monkeypatch.setattr(service_bastion, "provision_workspace", _provision)
    resp = client.post(
        "/admin/service/bastion/provision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code == 409


def test_provision_422_on_invalid_input(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _provision(login: str, ws_id: str) -> dict[str, Any]:
        raise ValueError("ws_id invalide")

    monkeypatch.setattr(service_bastion, "provision_workspace", _provision)
    resp = client.post(
        "/admin/service/bastion/provision", json={"login": "alice", "ws_id": "../etc"}
    )
    assert resp.status_code == 422


def test_provision_502_on_termix_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _provision(login: str, ws_id: str) -> dict[str, Any]:
        raise RuntimeError("Termix POST /host → 500")

    monkeypatch.setattr(service_bastion, "provision_workspace", _provision)
    resp = client.post(
        "/admin/service/bastion/provision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code == 502
    assert "Termix" in resp.json()["detail"]


def test_deprovision_nominal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _deprovision(login: str, ws_id: str) -> dict[str, Any]:
        return {"ws_id": ws_id, "removed": True, "termix_deleted": True}

    monkeypatch.setattr(service_bastion, "deprovision_workspace", _deprovision)
    resp = client.post(
        "/admin/service/bastion/deprovision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code == 200
    assert resp.json()["termix_deleted"] is True


def test_deprovision_502_on_termix_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _deprovision(login: str, ws_id: str) -> dict[str, Any]:
        raise RuntimeError("Termix DELETE /host/7 → 500")

    monkeypatch.setattr(service_bastion, "deprovision_workspace", _deprovision)
    resp = client.post(
        "/admin/service/bastion/deprovision", json={"login": "alice", "ws_id": "alice-proj"}
    )
    assert resp.status_code == 502


def test_body_extra_field_rejected(client: TestClient) -> None:
    resp = client.post(
        "/admin/service/bastion/provision",
        json={"login": "alice", "ws_id": "alice-proj", "extra": 1},
    )
    assert resp.status_code == 422
