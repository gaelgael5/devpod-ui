"""Routes page Utilisateurs admin (spec 18 T4) : liste + rattachement instance (DB mockée)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.db.engine import get_conn
from portal.routes import admin_users
from portal.routes.admin_users import router


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    users = {
        "alice": {
            "login": "alice",
            "email": "a@x",
            "display_name": "Alice",
            "termix_instance_id": None,
        },
    }
    instances = {"i1"}

    async def _list_users(conn: Any) -> list[dict[str, Any]]:
        return list(users.values())

    async def _user_exists(login: str, conn: Any) -> bool:
        return login in users

    async def _set_instance(login: str, instance_id: str | None, conn: Any) -> bool:
        if login not in users:
            return False
        users[login]["termix_instance_id"] = instance_id
        return True

    async def _ti_get(conn: Any, instance_id: str) -> dict[str, Any] | None:
        return {"id": instance_id} if instance_id in instances else None

    monkeypatch.setattr(admin_users, "list_users_db", _list_users)
    monkeypatch.setattr(admin_users, "user_exists_db", _user_exists)
    monkeypatch.setattr(admin_users, "set_user_termix_instance_db", _set_instance)
    monkeypatch.setattr(admin_users.ti, "get", _ti_get)

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def test_list_users(client: TestClient) -> None:
    r = client.get("/admin/users")
    assert r.status_code == 200 and [u["login"] for u in r.json()] == ["alice"]


def test_assign_instance(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instance", json={"instance_id": "i1"})
    assert r.status_code == 200 and r.json() == {"instance_id": "i1"}
    # clear → null
    r2 = client.put("/admin/users/alice/termix-instance", json={"instance_id": None})
    assert r2.status_code == 200 and r2.json() == {"instance_id": None}


def test_assign_unknown_user_404(client: TestClient) -> None:
    r = client.put("/admin/users/ghost/termix-instance", json={"instance_id": "i1"})
    assert r.status_code == 404


def test_assign_unknown_instance_422(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instance", json={"instance_id": "nope"})
    assert r.status_code == 422


def test_assign_rejects_extra_field(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instance", json={"instance_id": "i1", "x": 1})
    assert r.status_code == 422


def test_requires_admin() -> None:
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_conn] = lambda: None
    c = TestClient(app)
    assert c.get("/admin/users").status_code in (401, 403)
