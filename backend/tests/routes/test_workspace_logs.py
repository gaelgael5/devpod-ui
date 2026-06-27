from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

FAKE_DEVPOD = Path(__file__).parent.parent / "devpod" / "fake_devpod.py"


def _build_global_config(tmp_path: Path) -> None:
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


async def _provision_alice(tmp_path: Path) -> None:
    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)


def _make_app(tmp_path: Path):
    import portal.auth.router as auth_router_mod
    import portal.routes.workspace_ops as ws_ops_mod
    import portal.settings as settings_mod

    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    settings_mod._settings = None
    auth_router_mod._oidc_client = None
    ws_ops_mod._reset_service()

    _build_global_config(tmp_path)
    asyncio.run(_provision_alice(tmp_path))

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user

    app = create_app()
    user = UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[require_user] = lambda: user
    return app


# ---------------------------------------------------------------------------
# Tests GET /me/workspaces/{name}/logs
# ---------------------------------------------------------------------------


def test_get_workspace_logs_not_found(tmp_path: Path) -> None:
    """404 quand le fichier de logs n'existe pas."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/logs")
    assert resp.status_code == 404


def test_get_workspace_logs_returns_content(tmp_path: Path) -> None:
    """200 + contenu du fichier de logs quand il existe."""
    app = _make_app(tmp_path)

    # Créer le fichier de logs à l'emplacement attendu : logs/{login}/{ws_id}.log
    log_dir = tmp_path / "logs" / "alice"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_content = "ligne 1\nligne 2\nligne 3\n"
    (log_dir / "alice-myapp.log").write_text(log_content, encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/logs")

    assert resp.status_code == 200
    assert resp.text == log_content


def test_get_workspace_logs_truncates_to_100k(tmp_path: Path) -> None:
    """Le contenu est tronqué aux 100 000 derniers caractères si le fichier est plus grand."""
    app = _make_app(tmp_path)

    log_dir = tmp_path / "logs" / "alice"
    log_dir.mkdir(parents=True, exist_ok=True)
    # Générer un contenu de 150 000 caractères
    line = "x" * 99 + "\n"  # 100 chars par ligne
    big_content = line * 1500  # 150 000 chars
    (log_dir / "alice-myapp.log").write_text(big_content, encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/logs")

    assert resp.status_code == 200
    assert len(resp.text) == 100_000
    # La troncature garde la FIN du fichier
    assert resp.text == big_content[-100_000:]


def test_get_workspace_logs_rejects_invalid_name(tmp_path: Path) -> None:
    """422 pour un name invalide (majuscules, underscore…)."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/INVALID_NAME/logs")
    assert resp.status_code == 422
