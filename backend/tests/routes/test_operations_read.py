"""Lecture REST d'une opération — et son cloisonnement."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.routes import operations


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(operations.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])

    async def _get(operation_id: str) -> dict[str, Any] | None:
        registre = {
            "op-a-moi": {"operation_id": "op-a-moi", "state": "done", "owner_login": "admin"},
            "op-a-un-autre": {
                "operation_id": "op-a-un-autre",
                "state": "done",
                "owner_login": "bob",
            },
        }
        return registre.get(operation_id)

    monkeypatch.setattr(operations, "get_operation", _get)
    return TestClient(app)


def test_lit_son_operation(client: TestClient) -> None:
    res = client.get("/admin/operations/op-a-moi")

    assert res.status_code == 200
    assert res.json()["state"] == "done"


def test_ne_lit_pas_celle_d_un_autre(client: TestClient) -> None:
    # Cloisonnement : l'identifiant est un UUID, mais on ne fait pas reposer
    # l'isolation sur le fait qu'il soit difficile a deviner.
    assert client.get("/admin/operations/op-a-un-autre").status_code == 404


def test_operation_inexistante(client: TestClient) -> None:
    # Meme code que « pas a vous » : distinguer renseignerait sur les autres.
    assert client.get("/admin/operations/fantome").status_code == 404
