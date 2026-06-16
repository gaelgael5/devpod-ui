from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient


def _provision_alice(tmp_path: Path) -> None:
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)

    async def _inner() -> None:
        from portal.auth.router import provision_user

        await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)

    asyncio.run(_inner())


def _make_app(tmp_path: Path, role: str = "dev") -> TestClient:
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin, require_user

    app = create_app()
    user = UserInfo(login="alice", roles=[role])
    app.dependency_overrides[require_user] = lambda: user
    if role == "admin":
        app.dependency_overrides[require_admin] = lambda: user
    return app


def test_get_me_returns_login_and_roles(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path, role="dev")
    with TestClient(app) as client:
        resp = client.get("/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["login"] == "alice"
    assert data["roles"] == ["dev"]


def test_get_me_admin_returns_admin_role(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path, role="admin")
    with TestClient(app) as client:
        resp = client.get("/me")
    assert resp.status_code == 200
    assert "admin" in resp.json()["roles"]


def test_get_me_config_returns_user_config(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/config")
    assert resp.status_code == 200
    assert "secret_ns" in resp.json()


def test_put_me_config_updates_defaults(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    payload = {"defaults": {"ide": "openvscode", "idle_timeout": "2h"}}
    with TestClient(app) as client:
        resp = client.put("/me/config", json=payload)
    assert resp.status_code == 200


def test_put_me_config_rejects_unknown_field(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.put("/me/config", json={"unknown_field": "value"})
    assert resp.status_code == 422


def test_get_me_workspaces_returns_empty_list(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces")
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_me_workspace_adds_workspace(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    with TestClient(app) as client:
        resp = client.post("/me/workspaces", json=ws)
    assert resp.status_code == 201
    with TestClient(app) as client:
        resp2 = client.get("/me/workspaces")
    assert any(w["name"] == "myapp" for w in resp2.json())


def test_delete_me_workspace_removes_workspace(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    ws = {"name": "todelete", "source": "git@github.com:user/repo.git"}
    with TestClient(app) as client:
        client.post("/me/workspaces", json=ws)
        resp = client.delete("/me/workspaces/todelete")
    assert resp.status_code == 200
    with TestClient(app) as client:
        resp2 = client.get("/me/workspaces")
    assert not any(w["name"] == "todelete" for w in resp2.json())


def test_get_git_credentials_includes_username(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/me/git-credentials", json={
            "name": "gh", "host": "github.com", "kind": "token",
            "username": "oauth2", "token": "ghp_test123",
        })
        resp = client.get("/me/git-credentials")
    assert resp.status_code == 200
    creds = resp.json()
    assert len(creds) == 1
    assert creds[0]["username"] == "oauth2"


def test_require_user_blocks_unauthenticated(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["DEV_MODE"] = "true"
    mod._settings = None

    try:
        from portal.app import create_app

        app = create_app()  # no dependency_overrides
        with TestClient(app) as client:
            resp = client.get("/me/config")
        assert resp.status_code == 401
    finally:
        os.environ.pop("DEV_MODE", None)
        mod._settings = None
