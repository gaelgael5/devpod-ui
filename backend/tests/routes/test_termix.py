"""Routes registre d'instances Termix : validations + CRUD (DB mockée)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from portal.auth.rbac import UserInfo, require_admin
from portal.db.engine import get_conn
from portal.routes import termix
from portal.routes.termix import InstanceCreate, router


def test_create_model_requires_non_empty() -> None:
    with pytest.raises(ValidationError):
        InstanceCreate(name=" ", url="https://x", apikey_secret="s")
    with pytest.raises(ValidationError):
        InstanceCreate(name="a", url="https://x", apikey_secret="  ")
    with pytest.raises(ValidationError):
        InstanceCreate(name="a", url="https://x", apikey_secret="s", extra=1)  # type: ignore[call-arg]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store: dict[str, dict[str, Any]] = {}

    async def _name_exists(conn: Any, name: str, *, exclude_id: str | None = None) -> bool:
        return any(v["name"] == name and k != exclude_id for k, v in store.items())

    async def _create(conn: Any, **f: Any) -> dict[str, Any]:
        rid = f"id{len(store)}"
        row = {"id": rid, "is_default": False, "oidc_client_id": "", **f}
        if row.get("is_default"):
            for v in store.values():
                v["is_default"] = False
        store[rid] = row
        return row

    async def _get(conn: Any, rid: str) -> dict[str, Any] | None:
        return store.get(rid)

    async def _list_all(conn: Any) -> list[dict[str, Any]]:
        return sorted(store.values(), key=lambda r: r["name"])

    async def _delete(conn: Any, rid: str) -> bool:
        return store.pop(rid, None) is not None

    monkeypatch.setattr(termix.ti, "name_exists", _name_exists)
    monkeypatch.setattr(termix.ti, "create", _create)
    monkeypatch.setattr(termix.ti, "get", _get)
    monkeypatch.setattr(termix.ti, "list_all", _list_all)
    monkeypatch.setattr(termix.ti, "delete_instance", _delete)

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def test_create_list_and_default(client: TestClient) -> None:
    r = client.post(
        "/admin/termix-instances",
        json={"name": "local", "url": "https://termix.yoops.org", "apikey_secret": "termix"},
    )
    assert r.status_code == 201 and r.json()["name"] == "local"
    # doublon de nom → 409
    dup = client.post(
        "/admin/termix-instances",
        json={"name": "local", "url": "https://x", "apikey_secret": "s"},
    )
    assert dup.status_code == 409
    # url non http(s) → 422
    bad = client.post(
        "/admin/termix-instances",
        json={"name": "x", "url": "ftp://x", "apikey_secret": "s"},
    )
    assert bad.status_code == 422
    lst = client.get("/admin/termix-instances")
    assert [i["name"] for i in lst.json()] == ["local"]


def test_delete_404(client: TestClient) -> None:
    assert client.delete("/admin/termix-instances/nope").status_code == 404


def test_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_conn] = lambda: None
    client = TestClient(app)
    assert client.get("/admin/termix-instances").status_code in (401, 403)
