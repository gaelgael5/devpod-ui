"""Routes page Utilisateurs admin (spec 18 T4b) : liste + rattachement N-N ≤3 (DB mockée)."""

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
    users = {"alice"}
    instances = {"i1", "i2", "i3", "i4"}
    assigned: dict[str, list[str]] = {}

    async def _list_users(conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "login": "alice",
                "email": "a@x",
                "display_name": "Alice",
                "termix_instance_ids": assigned.get("alice", []),
            }
        ]

    async def _user_exists(login: str, conn: Any) -> bool:
        return login in users

    async def _ti_get(conn: Any, instance_id: str) -> dict[str, Any] | None:
        return {"id": instance_id} if instance_id in instances else None

    async def _set(conn: Any, login: str, ids: list[str]) -> None:
        assigned[login] = list(ids)

    async def _list_ids(conn: Any, login: str) -> list[str]:
        return sorted(assigned.get(login, []))

    monkeypatch.setattr(admin_users, "list_users_db", _list_users)
    monkeypatch.setattr(admin_users, "user_exists_db", _user_exists)
    monkeypatch.setattr(admin_users.ti, "get", _ti_get)
    monkeypatch.setattr(admin_users.uti, "set_instances_for_user", _set)
    monkeypatch.setattr(admin_users.uti, "list_instance_ids", _list_ids)

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def test_list_users(client: TestClient) -> None:
    r = client.get("/admin/users")
    assert r.status_code == 200 and r.json()[0]["login"] == "alice"


def test_assign_instances(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instances", json={"instance_ids": ["i1", "i2"]})
    assert r.status_code == 200 and r.json() == {"instance_ids": ["i1", "i2"]}


def test_assign_unknown_user_404(client: TestClient) -> None:
    r = client.put("/admin/users/ghost/termix-instances", json={"instance_ids": ["i1"]})
    assert r.status_code == 404


def test_assign_unknown_instance_422(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instances", json={"instance_ids": ["nope"]})
    assert r.status_code == 422


def test_assign_over_cap_422(client: TestClient) -> None:
    r = client.put(
        "/admin/users/alice/termix-instances",
        json={"instance_ids": ["i1", "i2", "i3", "i4"]},
    )
    assert r.status_code == 422


def test_assign_rejects_extra_field(client: TestClient) -> None:
    r = client.put(
        "/admin/users/alice/termix-instances", json={"instance_ids": [], "x": 1}
    )
    assert r.status_code == 422


def test_requires_admin() -> None:
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_conn] = lambda: None
    c = TestClient(app)
    assert c.get("/admin/users").status_code in (401, 403)
