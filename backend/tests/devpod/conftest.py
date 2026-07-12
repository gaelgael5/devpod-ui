from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

FAKE_DEVPOD = Path(__file__).parent / "fake_devpod.py"


@pytest.fixture(autouse=True)
def _reset_runner_locks() -> None:
    """Vide les registres de verrous (runner + lifecycle) avant chaque test.

    Un asyncio.Lock module-level se lie à la première boucle qui l'acquiert ; sous
    pytest-asyncio (une boucle par test) il faut repartir d'un registre vide.
    """
    from portal.devpod import runner, service

    runner.clear_locks()
    service.clear_lifecycle_locks()


@pytest.fixture
def fake_devpod_bin() -> list[str]:
    """Retourne la commande pour appeler le faux devpod."""
    return [sys.executable, str(FAKE_DEVPOD)]


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    """Moteur factice : begin()/connect() rendent un contexte async sans DB réelle."""

    def begin(self) -> _FakeConn:
        return _FakeConn()

    def connect(self) -> _FakeConn:
        return _FakeConn()


@pytest.fixture
def status_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Remplace la couche DB statut par un dict en mémoire (conn ignoré).

    Partagé par test_lifecycle_lock (bugs 003/007/041) et les tests de
    persistance de port (bug 001).
    """
    import portal.devpod.service as service_mod

    store: dict[str, dict[str, Any]] = {}

    async def fake_upsert(
        ws_id: str, status: str, conn: Any, login: str = "", **extra: Any
    ) -> None:
        store[ws_id] = {"ws_id": ws_id, "status": status, "login": login, **extra}

    async def fake_update_if_exists(
        ws_id: str, status: str, conn: Any, login: str = "", **extra: Any
    ) -> bool:
        if ws_id not in store:
            return False
        store[ws_id].update({"status": status, "login": login, **extra})
        return True

    async def fake_delete(ws_id: str, conn: Any) -> None:
        store.pop(ws_id, None)

    async def fake_get(ws_id: str, conn: Any) -> dict[str, Any] | None:
        return store.get(ws_id)

    async def fake_port_claimed_by_other(ws_id: str, port: int, conn: Any) -> bool:
        return any(r.get("host_port") == port and r["ws_id"] != ws_id for r in store.values())

    async def fake_persist_log(*args: Any, **kwargs: Any) -> None:
        return None

    class _FakeMsgDb:
        @staticmethod
        async def purge_workspace_messages(*args: Any, **kwargs: Any) -> None:
            return None

    async def fake_revoke_workspace_keys(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(service_mod, "revoke_workspace_keys", fake_revoke_workspace_keys)
    monkeypatch.setattr(service_mod, "upsert_status_db", fake_upsert)
    monkeypatch.setattr(service_mod, "update_status_if_exists_db", fake_update_if_exists)
    monkeypatch.setattr(service_mod, "delete_status_db", fake_delete)
    monkeypatch.setattr(service_mod, "get_status_db", fake_get)
    monkeypatch.setattr(service_mod, "port_claimed_by_other_db", fake_port_claimed_by_other)
    monkeypatch.setattr(service_mod, "persist_log_blob_from_file", fake_persist_log)
    monkeypatch.setattr(service_mod, "_msg_db", _FakeMsgDb())
    return store


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
            },
            {
                "name": "node-ssh",
                "default": False,
                "type": "ssh",
                "docker_host": "",
                "address": "devops@192.168.1.40",
                "host_cert_slug": "pve1-ssh-key",
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
