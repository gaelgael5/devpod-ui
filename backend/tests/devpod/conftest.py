from __future__ import annotations

import sys
from pathlib import Path

import pytest

FAKE_DEVPOD = Path(__file__).parent / "fake_devpod.py"


@pytest.fixture(autouse=True)
def _reset_runner_locks() -> None:
    """Vide le registre de verrous du runner avant chaque test."""
    from portal.devpod import runner

    runner.clear_locks()


@pytest.fixture
def fake_devpod_bin() -> list[str]:
    """Retourne la commande pour appeler le faux devpod."""
    return [sys.executable, str(FAKE_DEVPOD)]


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None
    return tmp_path


@pytest.fixture
def global_cfg(tmp_data_root: Path):
    """GlobalConfig minimal avec un host docker-tls et un host ssh."""
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
            "binary": "devpod",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": str(tmp_data_root / "certs" / "portal"),
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
            {
                "name": "node-ssh",
                "default": False,
                "type": "ssh",
                "docker_host": "",
                "address": "devops@192.168.1.40",
                "key_path": "/data/keys/hosts/pve1",
            },
        ],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "http://cfm:8000", "api_key": ""},
    }
    (tmp_data_root / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )
    from portal.config.store import load_global

    return load_global()
