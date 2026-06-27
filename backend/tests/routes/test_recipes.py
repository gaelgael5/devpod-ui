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
    assert resp.status_code == 401


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
    # httpx normalises `../other` → `/admin/other` before sending, so the
    # router receives recipe_id="other" (valid regex) and returns 404.
    # If a future client sends the raw `..` segment, _validate_recipe_id
    # will reject it with 422. Both outcomes are safe.
    assert resp.status_code in (404, 405, 422)


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


def test_admin_get_recipes_requires_admin(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_user_app(tmp_path)  # require_admin non overridé → 401 sans session
    with TestClient(app) as client:
        resp = client.get("/admin/recipes")
    assert resp.status_code == 401


def test_delete_personal_recipe_requires_auth(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_no_auth_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/me/recipes/something")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Filtre ?type= sur GET /recipes
# ---------------------------------------------------------------------------


def _write_shared_start_recipe(data_root: Path, recipe_id: str) -> None:
    recipe_dir = data_root / "recipes" / recipe_id
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": recipe_id, "type": "start", "description": "Start recipe"}),
        encoding="utf-8",
    )
    (recipe_dir / "start.sh").write_text(
        f"#!/usr/bin/env bash\nexec {recipe_id}\n", encoding="utf-8"
    )


def test_get_recipes_type_start_filter(tmp_path: Path) -> None:
    """GET /recipes?type=start retourne uniquement les recettes de type start."""
    _write_global_config(tmp_path)
    _write_shared_start_recipe(tmp_path, "claude-rc")
    shared_dir = tmp_path / "recipes"
    _write_recipe(shared_dir, "my-install")

    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/recipes?type=start")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["type"] == "start" for r in data)
    assert any(r["id"] == "claude-rc" for r in data)


def test_get_recipes_type_install_excludes_start(tmp_path: Path) -> None:
    """GET /recipes?type=install exclut les recettes de type start."""
    _write_global_config(tmp_path)
    _write_shared_start_recipe(tmp_path, "claude-rc")

    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/recipes?type=install")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["id"] != "claude-rc" for r in data)


# ---------------------------------------------------------------------------
# POST /me/start-recipes
# ---------------------------------------------------------------------------


def _write_user_config(tmp_path: Path, login: str = "alice") -> None:
    user_dir = tmp_path / "users" / login
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "config.yaml").write_text(
        yaml.dump({
            "version": "1",
            "secret_ns": "00000000-0000-0000-0000-000000000001",
            "defaults": {}, "harpocrate": {}, "git_credentials": [], "workspaces": [],
        }),
        encoding="utf-8",
    )


def test_post_me_start_recipe_creates_recipe(tmp_path: Path) -> None:
    """POST /me/start-recipes crée la recette start sur disque et retourne 201."""
    _write_global_config(tmp_path)
    _write_user_config(tmp_path)

    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/start-recipes",
            json={
                "id": "my-start",
                "description": "Mon script",
                "script": "#!/bin/bash\necho ok\n",
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "my-start"
    assert data["type"] == "start"

    recipe_path = tmp_path / "users" / "alice" / "recipes" / "my-start"
    assert (recipe_path / "recipe.meta.yaml").exists()
    assert (recipe_path / "start.sh").exists()


def test_post_me_start_recipe_invalid_id(tmp_path: Path) -> None:
    """POST /me/start-recipes avec un id invalide retourne 422."""
    _write_global_config(tmp_path)
    _write_user_config(tmp_path)

    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/start-recipes",
            json={"id": "INVALID NAME!", "script": "echo ok"},
        )
    assert resp.status_code == 422


def test_post_me_start_recipe_conflict(tmp_path: Path) -> None:
    """POST /me/start-recipes avec un id déjà existant retourne 409."""
    _write_global_config(tmp_path)
    _write_user_config(tmp_path)
    # Pré-créer la recette
    recipe_dir = tmp_path / "users" / "alice" / "recipes" / "existing"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "existing", "type": "start", "description": "Existing"}),
        encoding="utf-8",
    )
    (recipe_dir / "start.sh").write_text("#!/bin/bash\necho existing\n", encoding="utf-8")

    app = _make_user_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/start-recipes",
            json={"id": "existing", "script": "#!/bin/bash\necho ok\n"},
        )
    assert resp.status_code == 409
