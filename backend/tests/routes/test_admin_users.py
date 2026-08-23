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
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    users = {"alice"}
    instances = {"i1", "i2", "i3", "i4", "idef"}
    assigned: dict[str, list[str]] = {}
    calls: list[tuple[str, Any]] = []

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

    async def _resolve(conn: Any, login: str) -> list[dict[str, Any]]:
        # Sémantique réelle : explicites, sinon héritage de l'instance défaut `idef`.
        ids = assigned.get(login, [])
        return [{"id": i} for i in ids] if ids else [{"id": "idef"}]

    async def _ensure_account(conn: Any, login: str, ids: list[str]) -> list[str]:
        calls.append(("ensure", list(ids)))
        return []

    async def _provision_access(conn: Any, login: str) -> list[str]:
        calls.append(("provision", login))
        return []

    async def _deprovision(conn: Any, login: str, instance_id: str) -> list[str]:
        calls.append(("deprovision", instance_id))
        return []

    async def _sync_servers(login: str) -> None:
        calls.append(("sync_servers", login))
        return None

    # La route PUT gère ses propres transactions (_get_engine().begin()/connect()) pour
    # committer l'association AVANT le provisioning synchrone → on mocke l'engine par un
    # faux dont le contexte cède une conn None (les fonctions DB ci-dessus l'ignorent).
    class _FakeCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: object) -> bool:
            return False

    class _FakeEngine:
        def begin(self) -> _FakeCtx:
            return _FakeCtx()

        def connect(self) -> _FakeCtx:
            return _FakeCtx()

    monkeypatch.setattr(admin_users, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(admin_users, "sync_server_hosts_for_user", _sync_servers)
    monkeypatch.setattr(admin_users, "list_users_db", _list_users)
    monkeypatch.setattr(admin_users, "user_exists_db", _user_exists)
    monkeypatch.setattr(admin_users, "ensure_termix_account", _ensure_account)
    monkeypatch.setattr(admin_users, "provision_user_access", _provision_access)
    monkeypatch.setattr(admin_users, "deprovision_user_from_instance", _deprovision)
    monkeypatch.setattr(admin_users.ti, "get", _ti_get)
    monkeypatch.setattr(admin_users.uti, "set_instances_for_user", _set)
    monkeypatch.setattr(admin_users.uti, "list_instance_ids", _list_ids)
    monkeypatch.setattr(admin_users.uti, "resolve_instances_for_user", _resolve)

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return {"client": TestClient(app), "calls": calls, "assigned": assigned}


@pytest.fixture
def client(env: dict[str, Any]) -> TestClient:
    return env["client"]


def test_list_users(client: TestClient) -> None:
    r = client.get("/admin/users")
    assert r.status_code == 200 and r.json()[0]["login"] == "alice"


def test_assign_instances(client: TestClient) -> None:
    r = client.put("/admin/users/alice/termix-instances", json={"instance_ids": ["i1", "i2"]})
    assert r.status_code == 200
    assert r.json() == {"instance_ids": ["i1", "i2"], "termix_warnings": []}


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
    r = client.put("/admin/users/alice/termix-instances", json={"instance_ids": [], "x": 1})
    assert r.status_code == 422


def test_deassociate_default_inherited_is_noop(env: dict[str, Any]) -> None:
    """Retirer l'instance défaut explicite → l'user en HÉRITE encore (vide = défaut) :
    aucun deprovision (sinon les hosts sont détruits puis recréés par le sync — le
    « serveur de test qui réapparaît »)."""
    env["assigned"]["alice"] = ["idef"]
    r = env["client"].put("/admin/users/alice/termix-instances", json={"instance_ids": []})
    assert r.status_code == 200
    kinds = [k for k, _ in env["calls"]]
    assert "deprovision" not in kinds
    assert ("ensure", ["idef"]) in env["calls"]  # comptes assurés sur l'instance effective


def test_deassociate_nondefault_deprovisions_it(env: dict[str, Any]) -> None:
    """Retirer une instance non-défaut → deprovision de CELLE-CI, et provisioning sur
    l'instance effective (héritage du défaut)."""
    env["assigned"]["alice"] = ["i2"]
    r = env["client"].put("/admin/users/alice/termix-instances", json={"instance_ids": []})
    assert r.status_code == 200
    assert ("deprovision", "i2") in env["calls"]
    assert ("ensure", ["idef"]) in env["calls"]


def test_deprovision_runs_before_provisioning(env: dict[str, Any]) -> None:
    """Bascule i2 → i3 : le nettoyage de l'instance retirée précède le provisioning
    (sinon un provisioning fantôme peut être détruit juste après sa création)."""
    env["assigned"]["alice"] = ["i2"]
    r = env["client"].put("/admin/users/alice/termix-instances", json={"instance_ids": ["i3"]})
    assert r.status_code == 200
    kinds = [k for k, _ in env["calls"]]
    assert kinds.index("deprovision") < kinds.index("ensure")
    assert kinds.index("deprovision") < kinds.index("provision")
    assert ("deprovision", "i2") in env["calls"] and ("deprovision", "i3") not in env["calls"]
    assert ("sync_servers", "alice") in env["calls"]


def test_requires_admin() -> None:
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_conn] = lambda: None
    c = TestClient(app)
    assert c.get("/admin/users").status_code in (401, 403)
