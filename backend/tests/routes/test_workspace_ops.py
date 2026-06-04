from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

FAKE_DEVPOD = Path(__file__).parent.parent / "devpod" / "fake_devpod.py"


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
    import portal.settings as settings_mod

    # Configurer l'environnement
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    settings_mod._settings = None
    auth_router_mod._oidc_client = None

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
    assert resp.status_code in (404, 422)


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
