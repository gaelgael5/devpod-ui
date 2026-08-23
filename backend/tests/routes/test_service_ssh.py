"""Endpoints service de consommation SSH (T4) : auth admin/clé API + shapes + reveal.

Auth réelle testée (rejet sans identité) ; les lectures sont monkeypatchées →
tournent sans Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin_or_api_key
from portal.db.engine import get_conn
from portal.routes import service_ssh
from portal.routes.service_ssh import router as service_ssh_router


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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _hosts(conn: Any) -> list[tuple[str, str, str, str]]:
        return [("alice", "proj", "host-test-1", "vm-alias")]

    async def _running(conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "ws_id": "alice-proj",
                "login": "alice",
                "host_name": "node-1",
                "hostname": "1.2.3.4",
                "status": "running",
            }
        ]

    async def _probe(login: str, ws_id: str) -> tuple[int, list[str]]:
        return (0, ["work", "logs"])

    async def _audit(*a: object, **k: object) -> None:
        return None

    async def _reveal(slug: str, conn: Any) -> str:
        return "s3cret"

    monkeypatch.setattr(service_ssh, "list_all_test_hosts", _hosts)
    monkeypatch.setattr(service_ssh, "list_running_db", _running)
    monkeypatch.setattr(service_ssh, "probe_workspace_sessions", _probe)
    monkeypatch.setattr(service_ssh, "audit_record", _audit)
    monkeypatch.setattr(service_ssh, "reveal_system_secret", _reveal)
    monkeypatch.setattr(service_ssh, "_get_engine", lambda: _FakeEngine())
    _host_cfg = SimpleNamespace(name="host-test-1", address="root@1.2.3.4")
    monkeypatch.setattr(
        service_ssh, "load_global", lambda: SimpleNamespace(hosts=[_host_cfg])
    )

    app = FastAPI()
    app.include_router(service_ssh_router, prefix="/admin/service")
    app.dependency_overrides[require_admin_or_api_key] = lambda: UserInfo(
        login="__api__", roles=["admin"]
    )
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def test_list_hosts_returns_ssh_coords(client: TestClient) -> None:
    resp = client.get("/admin/service/ssh/hosts")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "login": "alice",
            "workspace": "proj",
            "host_name": "host-test-1",
            "alias": "vm-alias",
            "address": "root@1.2.3.4",
            "has_password": True,
        }
    ]


def test_list_workspaces(client: TestClient) -> None:
    resp = client.get("/admin/service/ssh/workspaces")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["ws_id"] == "alice-proj"
    assert row["workspace"] == "proj"
    assert row["node"] == "node-1"


def test_list_sessions(client: TestClient) -> None:
    resp = client.get("/admin/service/ssh/sessions")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["workspace"] == "proj"
    assert row["sessions"] == ["work", "logs"]


def test_reveal_password(client: TestClient) -> None:
    resp = client.post("/admin/service/ssh/hosts/host-test-1/reveal-password")
    assert resp.status_code == 200
    assert resp.json() == {"password": "s3cret"}


def test_requires_auth() -> None:
    # Sans identité (ni clé API ni session admin) : rejet (401/403), aucune donnée exposée.
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(service_ssh_router, prefix="/admin/service")
    unauth = TestClient(app)
    resp = unauth.get("/admin/service/ssh/hosts")
    assert resp.status_code in (401, 403)
