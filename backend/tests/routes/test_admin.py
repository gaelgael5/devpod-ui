from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


def _write_global_config(tmp_data_root: Path) -> None:
    config = {
        "version": "1",
        "server": {
            "listen": "0.0.0.0:8080",
            "base_domain": "dev.yoops.org",
            "external_url": "https://dev.yoops.org",
            "dev_mode": False,
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
            "binary": "/usr/local/bin/devpod",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": "/data/certs/portal",
        },
        "hosts": [
            {
                "name": "local",
                "default": True,
                "type": "docker-tls",
                "docker_host": "tcp://192.168.1.50:2376",
                "address": "",
                "key_path": "",
            }
        ],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_data_root / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


def _make_admin_app(tmp_data_root: Path):
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_data_root)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="bob", roles=["admin"])
    return app


def _make_dev_app(tmp_data_root: Path):
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_data_root)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    from portal.app import create_app

    return create_app()  # sans override require_admin → 403


def test_get_admin_config_returns_version(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/config")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1"


def test_get_admin_config_requires_admin(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_dev_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/config")
    assert resp.status_code == 401


def test_get_admin_hosts_returns_list(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/hosts")
    assert resp.status_code == 200
    assert any(h["name"] == "local" for h in resp.json())


def test_post_admin_hosts_adds_host(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    new_host = {
        "name": "pve1",
        "default": False,
        "type": "ssh",
        "address": "devops@192.168.1.40",
        "key_path": "/data/keys/hosts/pve1",
        "docker_host": "",
    }
    with TestClient(app) as client:
        resp = client.post("/admin/hosts", json=new_host)
    assert resp.status_code == 201
    with TestClient(app) as client:
        resp2 = client.get("/admin/hosts")
    assert any(h["name"] == "pve1" for h in resp2.json())
