"""Défaut global de limite mémoire des workspaces (enabler 59864c37)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import portal.routes.admin as admin_mod
from portal.auth.rbac import UserInfo, require_admin
from portal.config.models import DevpodConfig
from portal.db.engine import get_conn


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, Any]]:
    # GlobalConfig complet inutile ici : la route ne touche que cfg.devpod.
    state: dict[str, Any] = {"cfg": SimpleNamespace(devpod=DevpodConfig()), "saved": None}

    async def _save(cfg: Any, conn: Any) -> None:
        state["saved"] = cfg

    monkeypatch.setattr(admin_mod, "load_global", lambda: state["cfg"])
    monkeypatch.setattr(admin_mod, "save_global_db", _save)
    monkeypatch.setattr(admin_mod, "set_cached_global", lambda cfg: None)

    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="bob", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app), state


def test_get_returns_default_900m(client: tuple[TestClient, dict[str, Any]]) -> None:
    c, _ = client
    resp = c.get("/admin/workspace-defaults")
    assert resp.status_code == 200
    # Décision d'exploitation du 2026-07-26 : 900 Mo par défaut.
    assert resp.json() == {"memory_limit": "900m"}


def test_put_updates_and_persists(client: tuple[TestClient, dict[str, Any]]) -> None:
    c, state = client
    resp = c.put("/admin/workspace-defaults", json={"memory_limit": "2G"})
    assert resp.status_code == 200
    assert resp.json() == {"memory_limit": "2g"}  # casse normalisée
    assert state["saved"] is not None
    assert state["saved"].devpod.defaults.memory_limit == "2g"


def test_put_empty_disables_the_default(client: tuple[TestClient, dict[str, Any]]) -> None:
    c, state = client
    resp = c.put("/admin/workspace-defaults", json={"memory_limit": ""})
    assert resp.status_code == 200
    assert state["saved"].devpod.defaults.memory_limit == ""


def test_put_rejects_bad_format(client: tuple[TestClient, dict[str, Any]]) -> None:
    c, state = client
    resp = c.put("/admin/workspace-defaults", json={"memory_limit": "beaucoup"})
    assert resp.status_code == 422
    assert state["saved"] is None
