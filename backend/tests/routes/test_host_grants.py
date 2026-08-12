"""Routes portée user→host SSH (spec 18 T3) : validations + set (DB mockée)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.db.engine import get_conn
from portal.routes import host_grants
from portal.routes.host_grants import router


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    users = {"alice"}
    hosts = [
        {"ws_id": "ws-a", "login": "alice", "host_name": "node1", "ssh_port": 50001},
        {"ws_id": "ws-b", "login": "bob", "host_name": "node1", "ssh_port": 50002},
    ]
    granted: dict[str, list[str]] = {}

    async def _user_exists(login: str, conn: Any) -> bool:
        return login in users

    async def _list_hosts(conn: Any) -> list[dict[str, Any]]:
        return hosts

    async def _list_for_user(conn: Any, login: str) -> list[str]:
        return sorted(granted.get(login, []))

    async def _set_for_user(conn: Any, login: str, ws_ids: list[str]) -> None:
        granted[login] = list(ws_ids)

    monkeypatch.setattr(host_grants, "user_exists_db", _user_exists)
    monkeypatch.setattr(host_grants, "list_ssh_hosts_db", _list_hosts)
    monkeypatch.setattr(host_grants.grants, "list_hosts_for_user", _list_for_user)
    monkeypatch.setattr(host_grants.grants, "set_hosts_for_user", _set_for_user)

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def test_list_ssh_hosts(client: TestClient) -> None:
    r = client.get("/admin/ssh-hosts")
    assert r.status_code == 200
    assert [h["ws_id"] for h in r.json()] == ["ws-a", "ws-b"]


def test_get_grants_unknown_user_404(client: TestClient) -> None:
    assert client.get("/admin/users/ghost/host-grants").status_code == 404


def test_set_grants_replaces(client: TestClient) -> None:
    r = client.put("/admin/users/alice/host-grants", json={"hosts": ["ws-a", "ws-b"]})
    assert r.status_code == 200 and r.json() == {"hosts": ["ws-a", "ws-b"]}
    r2 = client.get("/admin/users/alice/host-grants")
    assert r2.json() == {"hosts": ["ws-a", "ws-b"]}


def test_set_grants_rejects_unknown_host(client: TestClient) -> None:
    r = client.put("/admin/users/alice/host-grants", json={"hosts": ["ws-a", "nope"]})
    assert r.status_code == 422


def test_set_grants_rejects_extra_field(client: TestClient) -> None:
    r = client.put("/admin/users/alice/host-grants", json={"hosts": [], "x": 1})
    assert r.status_code == 422


def test_requires_admin() -> None:
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_conn] = lambda: None
    c = TestClient(app)
    assert c.get("/admin/ssh-hosts").status_code in (401, 403)
