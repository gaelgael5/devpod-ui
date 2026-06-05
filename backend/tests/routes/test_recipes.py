# backend/tests/routes/test_recipes.py
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


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


def _write_recipe(base: Path, recipe_id: str, version: str = "1.0.0") -> None:
    d = base / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": recipe_id, "version": version, "description": f"Recipe {recipe_id}"}),
        encoding="utf-8",
    )
    (d / "devcontainer-feature.json").write_text(
        json.dumps({"id": recipe_id, "version": version}), encoding="utf-8"
    )
    (d / "install.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")


def _make_user_app(tmp_path: Path):
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


def _make_admin_app(tmp_path: Path):
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin, require_user

    app = create_app()
    app.dependency_overrides[require_user] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    return app


def _make_no_auth_app(tmp_path: Path):
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app

    return create_app()


def test_get_recipes_returns_shared_recipes(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    shared_dir = tmp_path / "recipes"
    _write_recipe(shared_dir, "claude-code")
    _write_recipe(shared_dir, "aider")
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/recipes")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert "claude-code" in ids
    assert "aider" in ids


def test_get_recipes_includes_personal(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    personal_dir = tmp_path / "users" / "alice" / "recipes"
    _write_recipe(personal_dir, "my-custom")
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/recipes")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert "my-custom" in ids


def test_get_recipes_requires_auth(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_no_auth_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/recipes")
    assert resp.status_code == 403


def test_delete_personal_recipe(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    personal_dir = tmp_path / "users" / "alice" / "recipes"
    _write_recipe(personal_dir, "my-custom")
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/me/recipes/my-custom")
    assert resp.status_code == 200
    assert not (personal_dir / "my-custom").exists()


def test_delete_personal_recipe_not_found(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/me/recipes/nonexistent")
    assert resp.status_code == 404


def test_admin_get_shared_recipes(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    shared_dir = tmp_path / "recipes"
    _write_recipe(shared_dir, "shared-tool")
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/recipes")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert "shared-tool" in ids


def test_admin_delete_shared_recipe(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    shared_dir = tmp_path / "recipes"
    _write_recipe(shared_dir, "shared-tool")
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/admin/recipes/shared-tool")
    assert resp.status_code == 200
    assert not (shared_dir / "shared-tool").exists()


def test_delete_shared_recipe_path_traversal_rejected(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/admin/recipes/../other")
    assert resp.status_code in (404, 422)


def test_admin_delete_recipe_not_found(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/admin/recipes/nonexistent")
    assert resp.status_code == 404


def test_delete_personal_recipe_invalid_id_rejected(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/me/recipes/INVALID!")
    assert resp.status_code == 422


def test_admin_delete_shared_recipe_invalid_id_rejected(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/admin/recipes/INVALID!")
    assert resp.status_code == 422
