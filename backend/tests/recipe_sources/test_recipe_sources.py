from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)


def _write_global_config(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "server": {
            "listen": "0.0.0.0:8080",
            "base_domain": "dev.yoops.org",
            "external_url": "https://dev.yoops.org",
            "dev_mode": True,
            "log": {"level": "info", "format": "text", "output": ""},
        },
        "auth": {
            "oidc": {
                "issuer": "https://kc.test",
                "client_id": "portal",
                "client_secret": "",
                "scopes": ["openid"],
                "role_claim": "realm_access.roles",
                "admin_role": "admin",
                "user_role": "dev",
                "username_claim": "preferred_username",
            }
        },
        "secrets": {
            "backend": "inline",
            "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"},
        },
        "devpod": {
            "binary": "devpod",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": "/data/certs/portal",
        },
        "hosts": [],
        "caddy": {"admin_api": ""},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_path / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


def _make_admin_app(tmp_path: Path) -> FastAPI:
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    return app


def _make_user_app(tmp_path: Path) -> FastAPI:
    """App with non-admin user — require_admin dependency NOT overridden."""
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user

    app = create_app()
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    return app


# Test 1: GET /admin/recipe-sources returns default source URL when no file exists
def test_get_recipe_sources_returns_default(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/recipe-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert _DEFAULT_SOURCE in data["sources"]


# Test 2: PUT /admin/recipe-sources replaces sources list
def test_put_recipe_sources_replaces_list(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    new_sources = [
        "https://example.com/toc.txt",
        "https://other.org/recipes/toc.txt",
    ]
    with TestClient(app) as client:
        resp = client.put("/admin/recipe-sources", json={"sources": new_sources})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == new_sources

    # Verify persistence on disk
    sources_file = tmp_path / "recipe-sources.yaml"
    assert sources_file.exists()
    on_disk = yaml.safe_load(sources_file.read_text(encoding="utf-8"))
    assert on_disk["sources"] == new_sources


# Test 3: GET after PUT returns updated sources
def test_get_after_put_returns_updated_sources(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    new_sources = ["https://custom.example.com/toc.txt"]
    with TestClient(app) as client:
        put_resp = client.put("/admin/recipe-sources", json={"sources": new_sources})
        assert put_resp.status_code == 200
        get_resp = client.get("/admin/recipe-sources")
    assert get_resp.status_code == 200
    assert get_resp.json()["sources"] == new_sources


# Test 4: GET /admin/recipe-sources returns 401 for non-admin user (no session)
def test_get_recipe_sources_requires_admin(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    # _make_user_app does NOT override require_admin → 401 (no session)
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/recipe-sources")
    assert resp.status_code == 401
