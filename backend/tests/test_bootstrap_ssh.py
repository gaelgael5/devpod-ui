from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request

# ── Config YAML de test ───────────────────────────────────────────────────────

_CONFIG = textwrap.dedent("""\
    version: "1"
    server:
      listen: "0.0.0.0:8080"
      base_domain: "dev.yoops.org"
      external_url: "https://dev.yoops.org"
      dev_mode: false
      log:
        level: "info"
        format: "text"
        output: ""
    auth:
      oidc:
        issuer: "https://security.yoops.org/realms/yoops"
        client_id: "workspace-portal"
        client_secret: "secret"
        scopes: ["openid", "profile", "email", "roles"]
        role_claim: "realm_access.roles"
        admin_role: "admin"
        user_role: "dev"
        username_claim: "preferred_username"
    secrets:
      backend: "inline"
    devpod:
      binary: "/usr/local/bin/devpod"
      defaults:
        ide: "openvscode"
        idle_timeout: "2h"
        dotfiles: ""
      client_cert_path: "/data/certs/portal"
    caddy:
      admin_api: "http://caddy:2019"
    cloudflare_manager:
      url: ""
      api_key: ""
    hosts:
      - name: "ssh-host"
        type: "ssh"
      - name: "docker-host"
        type: "docker-tls"
        docker_host: "tcp://192.168.1.50:2376"
    proxmox_nodes:
      - name: "pve1"
        address: "192.168.10.41"
        ssh_user: "root"
        ssh_port: 22
        ssh_key_path: "/data/ssh_keys/proxmox/pve1"
        pve_node: "pve"
    """)

_PAYLOAD = {"address": "debian@192.168.10.179", "proxmox_node": "pve1"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def data_root(tmp_data_root: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None
    (tmp_data_root / "config.yaml").write_text(_CONFIG)
    return tmp_data_root


def _admin_client(data_root: Path) -> TestClient:
    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    return client


def _anon_client(data_root: Path) -> TestClient:
    from portal.app import create_app
    return TestClient(create_app())


def _proc_ok() -> MagicMock:
    """Mock de processus SSH ayant réussi (returncode=0)."""
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.kill = MagicMock()
    return proc


def _proc_fail(msg: str = "Connection refused") -> MagicMock:
    """Mock de processus SSH ayant échoué (returncode=1)."""
    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", msg.encode()))
    proc.kill = MagicMock()
    return proc


# ── Tests nominaux ────────────────────────────────────────────────────────────

def test_bootstrap_returns_public_key_and_updates_config(data_root: Path) -> None:
    """Nominal : génère la clé, met à jour le config, retourne public_key + address + key_path."""
    from portal.config.store import load_global
    client = _admin_client(data_root)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["public_key"].startswith("ssh-ed25519 ")
    assert body["address"] == "debian@192.168.10.179"
    assert "ssh-host_ed25519" in body["key_path"]

    cfg = load_global()
    host = next(h for h in cfg.hosts if h.name == "ssh-host")
    assert host.address == "debian@192.168.10.179"
    assert "ssh-host_ed25519" in host.key_path


def test_bootstrap_creates_key_file(data_root: Path) -> None:
    """La clé privée est créée sur le filesystem."""
    client = _admin_client(data_root)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)

    key_path = data_root / "keys" / "hosts" / "ssh-host_ed25519"
    assert key_path.exists()


def test_bootstrap_idempotent_key(data_root: Path) -> None:
    """Deux appels successifs retournent la même clé publique."""
    client = _admin_client(data_root)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        r1 = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        r2 = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)

    assert r1.json()["public_key"] == r2.json()["public_key"]


def test_bootstrap_calls_ssh_inject(data_root: Path) -> None:
    """Le subprocess SSH est bien appelé lors du bootstrap."""
    client = _admin_client(data_root)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)

    assert resp.status_code == 200
    assert mock_exec.called


# ── Tests de rejet de validation ──────────────────────────────────────────────

def test_bootstrap_host_not_found(data_root: Path) -> None:
    """Host inexistant → 404."""
    client = _admin_client(data_root)
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/inexistant/bootstrap-ssh", json=_PAYLOAD)
    assert resp.status_code == 404


def test_bootstrap_wrong_type(data_root: Path) -> None:
    """Host docker-tls → 422."""
    client = _admin_client(data_root)
    payload = {"address": "debian@192.168.1.50", "proxmox_node": "pve1"}
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/docker-host/bootstrap-ssh", json=payload)
    assert resp.status_code == 422


def test_bootstrap_proxmox_node_not_found(data_root: Path) -> None:
    """Nœud PVE inexistant → 404."""
    client = _admin_client(data_root)
    payload = {"address": "debian@192.168.10.179", "proxmox_node": "pve-inexistant"}
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=payload)
    assert resp.status_code == 404


def test_bootstrap_invalid_address(data_root: Path) -> None:
    """Adresse avec caractères invalides → 422."""
    client = _admin_client(data_root)
    payload = {"address": "debian@host'; rm -rf /", "proxmox_node": "pve1"}
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_ok()
        resp = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=payload)
    assert resp.status_code == 422


# ── Tests d'authentification ──────────────────────────────────────────────────

def test_bootstrap_requires_admin_auth(data_root: Path) -> None:
    """Sans session → 401 ou 403."""
    resp = _anon_client(data_root).post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)
    assert resp.status_code in (401, 403)


# ── Tests de gestion des erreurs SSH ─────────────────────────────────────────

def test_bootstrap_ssh_inject_fails_returns_502(data_root: Path) -> None:
    """Échec de l'injection SSH → 502."""
    client = _admin_client(data_root)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = _proc_fail("Connection refused")
        resp = client.post("/admin/hosts/ssh-host/bootstrap-ssh", json=_PAYLOAD)

    assert resp.status_code == 502
    assert "Injection" in resp.json()["detail"]
