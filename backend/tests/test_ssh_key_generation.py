from __future__ import annotations

import sys
import textwrap
from pathlib import Path

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
    """)

_API_KEY = "test-api-key-12345"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def data_root(tmp_data_root: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("PORTAL_API_KEY", _API_KEY)
    import portal.settings as mod

    mod._settings = None
    (tmp_data_root / "config.yaml").write_text(_CONFIG)
    return tmp_data_root


def _anon_client(data_root: Path) -> TestClient:
    from portal.app import create_app

    return TestClient(create_app())


def _bearer_client(data_root: Path) -> TestClient:
    """Client avec Bearer token valide dans chaque requête."""
    from portal.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": f"Bearer {_API_KEY}"})
    return client


def _admin_session_client(data_root: Path) -> TestClient:
    """Client avec session admin (cookie)."""
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


# ── Tests nominaux ────────────────────────────────────────────────────────────


def test_generate_key_creates_file_and_returns_pubkey(data_root: Path) -> None:
    """Bearer valide → génère ed25519, stocke la privée à 0600, retourne la pub."""
    client = _bearer_client(data_root)
    resp = client.post("/admin/hosts/ssh-host/generate-ssh-key")
    assert resp.status_code == 200
    body = resp.json()
    assert "public_key" in body
    assert body["public_key"].startswith("ssh-ed25519 ")

    key_path = data_root / "keys" / "hosts" / "ssh-host_ed25519"
    assert key_path.exists()
    if sys.platform != "win32":
        assert (key_path.stat().st_mode & 0o777) == 0o600


def test_generate_key_updates_host_key_path(data_root: Path) -> None:
    """key_path du host est mis à jour dans config.yaml après génération."""
    from portal.config.store import load_global

    _bearer_client(data_root).post("/admin/hosts/ssh-host/generate-ssh-key")
    host = next(h for h in load_global().hosts if h.name == "ssh-host")
    assert "ssh-host_ed25519" in host.key_path


def test_generate_key_idempotent(data_root: Path) -> None:
    """Deux appels successifs retournent la même clé publique sans régénérer."""
    client = _bearer_client(data_root)
    r1 = client.post("/admin/hosts/ssh-host/generate-ssh-key")
    r2 = client.post("/admin/hosts/ssh-host/generate-ssh-key")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["public_key"] == r2.json()["public_key"]


def test_generate_key_via_admin_session(data_root: Path) -> None:
    """Un admin authentifié par session peut aussi appeler l'endpoint."""
    resp = _admin_session_client(data_root).post("/admin/hosts/ssh-host/generate-ssh-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"].startswith("ssh-ed25519 ")


# ── Tests de rejet d'auth ─────────────────────────────────────────────────────


def test_generate_key_requires_auth(data_root: Path) -> None:
    """Sans auth → 401."""
    resp = _anon_client(data_root).post("/admin/hosts/ssh-host/generate-ssh-key")
    assert resp.status_code == 401


def test_generate_key_invalid_bearer_token(data_root: Path) -> None:
    """Bearer token invalide → 401."""
    client = _anon_client(data_root)
    resp = client.post(
        "/admin/hosts/ssh-host/generate-ssh-key",
        headers={"Authorization": "Bearer MAUVAIS-TOKEN"},
    )
    assert resp.status_code == 401


# ── Tests du paramètre address ────────────────────────────────────────────────


def test_generate_key_sets_address(data_root: Path) -> None:
    """?address=... met à jour host.address dans config.yaml."""
    from portal.config.store import load_global

    _bearer_client(data_root).post(
        "/admin/hosts/ssh-host/generate-ssh-key?address=debian@192.168.1.50"
    )
    host = next(h for h in load_global().hosts if h.name == "ssh-host")
    assert host.address == "debian@192.168.1.50"


def test_generate_key_address_updated_when_key_exists(data_root: Path) -> None:
    """Clé déjà existante + nouvel address → address mis à jour sans régénérer la clé."""
    from portal.config.store import load_global

    client = _bearer_client(data_root)
    r1 = client.post("/admin/hosts/ssh-host/generate-ssh-key?address=debian@192.168.1.50")
    r2 = client.post("/admin/hosts/ssh-host/generate-ssh-key?address=debian@192.168.1.99")
    assert r1.json()["public_key"] == r2.json()["public_key"]
    host = next(h for h in load_global().hosts if h.name == "ssh-host")
    assert host.address == "debian@192.168.1.99"


# ── Tests de validation config ────────────────────────────────────────────────


def test_generate_key_host_not_found(data_root: Path) -> None:
    """Host inexistant → 404."""
    resp = _bearer_client(data_root).post("/admin/hosts/inexistant/generate-ssh-key")
    assert resp.status_code == 404


def test_generate_key_docker_tls_host(data_root: Path) -> None:
    """Host de type docker-tls → 422."""
    resp = _bearer_client(data_root).post("/admin/hosts/docker-host/generate-ssh-key")
    assert resp.status_code == 422
