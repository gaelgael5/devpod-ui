from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

FAKE_DEVPOD = Path(__file__).parent.parent / "devpod" / "fake_devpod.py"


@pytest.fixture(autouse=True)
def _mock_git_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock du pre-flight git : évite les appels réseau réels dans tous les tests."""
    import portal.routes.workspace_ops as ws_ops_mod

    monkeypatch.setattr(
        ws_ops_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(0, b"", b"")),
    )


def _build_global_config(tmp_path: Path) -> None:
    """Écrit un config.yaml global minimal dans tmp_path."""
    import yaml

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
            "binary": f"{sys.executable} {FAKE_DEVPOD}",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": str(tmp_path / "certs" / "portal"),
        },
        "hosts": [
            {
                "name": "local",
                "default": True,
                "type": "docker-tls",
                "docker_host": "tcp://192.168.1.50:2376",
                "address": "",
                "key_path": "",
            },
        ],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_path / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


def _make_app(tmp_path: Path):
    """Crée une app FastAPI configurée pour les tests avec alice provisionné."""
    import portal.auth.router as auth_router_mod
    import portal.routes.workspace_ops as ws_ops_mod
    import portal.settings as settings_mod

    # Configurer l'environnement
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    settings_mod._settings = None
    auth_router_mod._oidc_client = None
    # Réinitialiser le singleton du service pour que chaque test parte d'un état propre
    ws_ops_mod._reset_service()

    _build_global_config(tmp_path)
    asyncio.run(_provision_alice(tmp_path))

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user

    app = create_app()
    user = UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[require_user] = lambda: user
    return app


async def _provision_alice(tmp_path: Path) -> None:
    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)


def test_up_returns_202_with_ws_id(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git"},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["ws_id"] == "alice-myapp"
    assert data["status"] == "provisioning"


def test_status_returns_workspace_status(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    # Écrire un statut manuellement
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / "alice-myapp.json").write_text(
        json.dumps({"ws_id": "alice-myapp", "login": "alice", "status": "running"}),
        encoding="utf-8",
    )
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_up_rejects_unknown_host(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "host": "nonexistent-host",
            },
        )
    assert resp.status_code in (404, 400, 422)


def test_stop_rejects_path_traversal_name(tmp_path: Path) -> None:
    """stop() rejette un name contenant des séquences de traversal encodées."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/me/workspaces/..%2F..%2Fbob-app/stop")
    # URL-encoded traversal doit retourner 404 (FastAPI path routing le bloque)
    # ou 422 si le paramètre est décodé et soumis à _validate_name.
    assert resp.status_code in (404, 405, 422)


def test_stop_rejects_invalid_name(tmp_path: Path) -> None:
    """stop() rejette un name non DNS-safe (majuscules, underscore…)."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/me/workspaces/INVALID_NAME/stop")
    assert resp.status_code == 422


def test_delete_rejects_invalid_name(tmp_path: Path) -> None:
    """delete() rejette un name non DNS-safe."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/me/workspaces/INVALID_NAME/delete")
    assert resp.status_code == 422


def test_status_rejects_invalid_name(tmp_path: Path) -> None:
    """status() rejette un name non DNS-safe."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/INVALID_NAME/status")
    assert resp.status_code == 422


def _make_app_with_exposure_mock(tmp_path: Path):
    """Crée une app FastAPI avec ExposureService mocké."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import portal.auth.router as auth_router_mod
    import portal.routes.workspace_ops as ws_ops_mod
    import portal.settings as settings_mod

    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    settings_mod._settings = None
    auth_router_mod._oidc_client = None
    # Réinitialiser le singleton avant injection du mock
    ws_ops_mod._reset_service()

    _build_global_config(tmp_path)
    asyncio.run(_provision_alice(tmp_path))

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user
    from portal.exposure import ExposureService

    exposure_mock = MagicMock(spec=ExposureService)
    exposure_mock.allocate_port = AsyncMock(return_value=41000)
    exposure_mock.expose = AsyncMock(return_value="https://ws-alice-myapp.dev.yoops.org")
    exposure_mock.unexpose = AsyncMock()

    app = create_app()
    user = UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[require_user] = lambda: user

    from portal.devpod.service import DevPodService

    original_get_service = ws_ops_mod._get_service

    def patched_get_service() -> DevPodService:
        svc = original_get_service()
        svc._exposure = exposure_mock
        return svc

    ws_ops_mod._get_service = patched_get_service

    return app, exposure_mock, ws_ops_mod, original_get_service


def test_up_with_exposure_returns_202(tmp_path: Path) -> None:
    """up() avec ExposureService mocké retourne 202 + ws_id."""
    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/me/workspaces/myapp/up",
                json={"source": "git@github.com:user/repo.git"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["ws_id"] == "alice-myapp"
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


def test_delete_calls_unexpose(tmp_path: Path) -> None:
    """delete() appelle exposure.unexpose() avant de supprimer le workspace."""
    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        routes_dir = tmp_path / "routes"
        routes_dir.mkdir(parents=True, exist_ok=True)
        (routes_dir / "alice-myapp.json").write_text(
            json.dumps(
                {
                    "ws_id": "alice-myapp",
                    "login": "alice",
                    "status": "running",
                    "hostname": "ws-alice-myapp.dev.yoops.org",
                    "url": "https://ws-alice-myapp.dev.yoops.org",
                }
            ),
            encoding="utf-8",
        )
        with TestClient(app) as client:
            resp = client.post("/me/workspaces/myapp/delete")
        assert resp.status_code == 200
        exposure_mock.unexpose.assert_awaited_once_with("alice-myapp")
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


def test_stop_calls_unexpose(tmp_path: Path) -> None:
    """stop() appelle exposure.unexpose() avant d'arrêter le workspace."""
    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        with TestClient(app) as client:
            resp = client.post("/me/workspaces/myapp/stop")
        assert resp.status_code == 200
        exposure_mock.unexpose.assert_awaited_once_with("alice-myapp")
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


# ---------------------------------------------------------------------------
# Recipe wiring — tests d'intégration HTTP
# ---------------------------------------------------------------------------


def test_workspace_up_invalid_recipe_id_rejected(tmp_path: Path) -> None:
    """Recipe ID invalide rejeté avant tout accès disque (regex)."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git", "recipes": ["INVALID!"]},
        )
    assert resp.status_code == 422


def test_workspace_up_unknown_recipe_id_rejected(tmp_path: Path) -> None:
    """Recipe ID au format valide mais inconnu du registre → 422."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "recipes": ["nonexistent-recipe"],
            },
        )
    assert resp.status_code == 422


def test_workspace_up_empty_recipes_still_works(tmp_path: Path) -> None:
    """Pas de recettes → comportement nominal inchangé (202 + provisioning)."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git", "recipes": []},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["ws_id"] == "alice-myapp"
    assert data["status"] == "provisioning"


def test_get_ssh_key_returns_404_when_not_generated(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key retourne 404 si la clé n'existe pas."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/ssh-key")
    assert resp.status_code == 404


def test_get_ssh_key_returns_422_for_invalid_name(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key rejette les noms invalides."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/INVALID_NAME/ssh-key")
    assert resp.status_code == 422


def test_get_ssh_key_returns_200_when_key_exists(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key retourne 200 + public_key si la clé existe."""
    # _make_app provisionne alice (crée le répertoire user) et positionne PORTAL_DATA_ROOT
    app = _make_app(tmp_path)

    # Générer la clé directement via le module (simule DevPodService.up avec generate_ssh_key=True)
    from portal.ssh_keys import ensure_workspace_ssh_key

    expected_pub = ensure_workspace_ssh_key("alice", "myapp")

    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/ssh-key")

    assert resp.status_code == 200
    data = resp.json()
    assert "public_key" in data
    assert data["public_key"].startswith("ssh-ed25519 ")
    assert data["public_key"] == expected_pub


def test_up_with_generate_ssh_key_creates_key_file(tmp_path: Path) -> None:
    """POST up avec generate_ssh_key=True génère la paire de clés sur disque."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git", "generate_ssh_key": True},
        )
    assert resp.status_code == 202

    pub_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    assert pub_path.exists(), "La clé publique doit exister après up avec generate_ssh_key=True"
    assert pub_path.read_text(encoding="utf-8").strip().startswith("ssh-ed25519 ")


def test_up_without_generate_ssh_key_does_not_create_key(tmp_path: Path) -> None:
    """POST up sans generate_ssh_key ne crée pas de clé."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git"},
        )
    assert resp.status_code == 202

    pub_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    assert not pub_path.exists(), "Aucune clé ne doit être créée sans generate_ssh_key"


# ---------------------------------------------------------------------------
# Profile wiring — Task 4
# ---------------------------------------------------------------------------


def test_up_without_profile_field_is_retro_compatible(tmp_path: Path) -> None:
    """UpRequest sans 'profile' est accepté — rétro-compat."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git"},
        )
    assert resp.status_code == 202


def test_up_with_missing_profile_degrades_gracefully(tmp_path: Path) -> None:
    """Profil inexistant → 202 (pas d'erreur), workspace démarré sans profil."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "profile": {"scope": "user", "slug": "nonexistent"},
            },
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "provisioning"


def test_up_with_valid_profile_ref_returns_202(tmp_path: Path) -> None:
    """Profil existant dans /data/profiles → 202 et workspace lancé."""
    import yaml

    # Créer un profil partagé sur disque
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "python-dev.yaml").write_text(
        yaml.dump(
            {
                "name": "Python Dev",
                "description": "",
                "extensions": ["ms-python.python"],
                "settings": {},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "profile": {"scope": "shared", "slug": "python-dev"},
            },
        )
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Git pre-flight — test du rejet avant devpod up
# ---------------------------------------------------------------------------


def test_up_rejects_inaccessible_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-flight git échoué (exit 128) → 422 avant même de lancer devpod up."""
    import portal.routes.workspace_ops as ws_ops_mod

    monkeypatch.setattr(
        ws_ops_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(128, b"", b"fatal: repository not found")),
    )

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:private/repo.git"},
        )
    assert resp.status_code == 422
    assert "inaccessible" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Delete avec shelve — tests d'intégration
# ---------------------------------------------------------------------------


def test_delete_nothing_to_shelve_returns_no_branch(tmp_path: Path) -> None:
    """Suppression normale — recovery_branch None dans la réponse."""
    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        with patch(
            "portal.devpod.service.shelve_if_pending",
            AsyncMock(return_value=None),
        ), TestClient(app) as client:
            resp = client.post("/me/workspaces/myapp/delete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["recovery_branch"] is None
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


def test_delete_shelved_returns_branch(tmp_path: Path) -> None:
    """Suppression avec shelve — recovery_branch présent dans la réponse."""
    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        with patch(
            "portal.devpod.service.shelve_if_pending",
            AsyncMock(return_value="recovery-16-06-26-10-30"),
        ), TestClient(app) as client:
            resp = client.post("/me/workspaces/myapp/delete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["recovery_branch"] == "recovery-16-06-26-10-30"
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


def test_delete_push_failure_returns_409(tmp_path: Path) -> None:
    """Push échoue → 409, workspace non supprimé."""
    from fastapi import HTTPException

    app, exposure_mock, ws_ops_mod, original_get_service = _make_app_with_exposure_mock(tmp_path)
    try:
        with patch(
            "portal.devpod.service.shelve_if_pending",
            AsyncMock(side_effect=HTTPException(409, "Shelve impossible")),
        ), TestClient(app) as client:
            resp = client.post("/me/workspaces/myapp/delete")
        assert resp.status_code == 409
    finally:
        ws_ops_mod._get_service = original_get_service
        ws_ops_mod._reset_service()


# ---------------------------------------------------------------------------
# GET /workspaces/{name}/start-recipes
# ---------------------------------------------------------------------------


def test_get_workspace_start_recipes_returns_list(tmp_path: Path) -> None:
    """GET /workspaces/{name}/start-recipes retourne les start recipes attachées."""
    import yaml

    # Créer une recette start partagée
    recipe_dir = tmp_path / "recipes" / "claude-rc"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "claude-rc", "type": "start", "description": "Claude RC"}),
        encoding="utf-8",
    )
    (recipe_dir / "start.sh").write_text("#!/bin/bash\nexec claude --rc\n", encoding="utf-8")

    app = _make_app(tmp_path)

    # Mettre à jour le config utilisateur alice pour référencer la recette start
    login = "alice"
    ws_name = "my-ws"
    user_dir = tmp_path / "users" / login
    user_config_path = user_dir / "config.yaml"
    user_cfg = yaml.safe_load(user_config_path.read_text(encoding="utf-8"))
    user_cfg["workspaces"] = [
        {
            "name": ws_name,
            "source": "https://github.com/x/y",
            "start_recipes": ["claude-rc"],
        }
    ]
    user_config_path.write_text(yaml.dump(user_cfg), encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get(f"/me/workspaces/{ws_name}/start-recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["id"] == "claude-rc" for r in data)


def test_get_workspace_start_recipes_returns_empty_list(tmp_path: Path) -> None:
    """GET /workspaces/{name}/start-recipes retourne [] si start_recipes est vide."""
    import yaml

    app = _make_app(tmp_path)

    login = "alice"
    ws_name = "empty-ws"
    user_dir = tmp_path / "users" / login
    user_config_path = user_dir / "config.yaml"
    user_cfg = yaml.safe_load(user_config_path.read_text(encoding="utf-8"))
    user_cfg["workspaces"] = [
        {
            "name": ws_name,
            "source": "https://github.com/x/y",
        }
    ]
    user_config_path.write_text(yaml.dump(user_cfg), encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get(f"/me/workspaces/{ws_name}/start-recipes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_workspace_start_recipes_404_if_not_found(tmp_path: Path) -> None:
    """GET /workspaces/{name}/start-recipes retourne 404 si le workspace n'existe pas."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/nonexistent/start-recipes")
    assert resp.status_code == 404
