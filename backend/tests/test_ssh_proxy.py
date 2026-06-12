from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

# ── Fixtures ──────────────────────────────────────────────────────────────────

SSH_HOST_CONFIG = textwrap.dedent("""\
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
      - name: "ssh-dev"
        type: "ssh"
        address: "debian@192.168.10.175"
        key_path: '{key_path}'
      - name: "docker-local"
        type: "docker-tls"
        docker_host: "tcp://192.168.1.50:2376"
    """)


@pytest.fixture
def data_root_with_ssh(tmp_data_root: Path, monkeypatch) -> Path:
    """Répertoire temporaire avec config SSH et clé factice."""
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None

    key_dir = tmp_data_root / "keys" / "hosts"
    key_dir.mkdir(parents=True)
    key_file = key_dir / "ssh_dev_ed25519"
    key_file.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    key_file.chmod(0o600)

    config = SSH_HOST_CONFIG.format(key_path=key_file.as_posix())
    (tmp_data_root / "config.yaml").write_text(config)
    return tmp_data_root


def _inject_admin_session(app) -> TestClient:
    """Ajoute un endpoint POST /_test/login pour injecter une session admin sans passer par OIDC."""
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _test_login(request: Request):
        request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    return client


def _make_client(data_root_with_ssh: Path, as_admin: bool = True) -> TestClient:
    """Crée un TestClient avec session admin (ou non)."""
    from portal.app import create_app

    app = create_app()
    if as_admin:
        return _inject_admin_session(app)

    client = TestClient(app)
    return client


def _assert_ws_closes_with(client: TestClient, path: str, expected_code: int) -> None:
    """Connecte en WebSocket, tente de lire, vérifie le code de fermeture."""
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(path) as ws:
        ws.receive_text()
    assert exc_info.value.code == expected_code


# ── Tests d'authentification ──────────────────────────────────────────────────

def test_ws_rejects_unauthenticated(data_root_with_ssh):
    from portal.app import create_app
    app = create_app()
    client = TestClient(app)  # pas de login → pas de session

    _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4001)


def test_ws_rejects_non_admin(data_root_with_ssh):
    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login-user")
    async def _login_user(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login-user")

    _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4001)


# ── Tests de validation de la config ─────────────────────────────────────────

def test_ws_rejects_unknown_host(data_root_with_ssh):
    client = _make_client(data_root_with_ssh)
    _assert_ws_closes_with(client, "/admin/hosts/inexistant/ssh", 4004)


def test_ws_rejects_docker_tls_host(data_root_with_ssh):
    client = _make_client(data_root_with_ssh)
    _assert_ws_closes_with(client, "/admin/hosts/docker-local/ssh", 4022)


def test_ws_rejects_empty_key_path(tmp_data_root, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None

    config = SSH_HOST_CONFIG.format(key_path="")
    (tmp_data_root / "config.yaml").write_text(config)

    from portal.app import create_app
    app = create_app()
    client = _inject_admin_session(app)

    _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4022)


def test_ws_rejects_key_path_outside_data_root(tmp_data_root, monkeypatch):
    import tempfile

    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None

    # Crée un répertoire totalement séparé de tmp_data_root
    with tempfile.TemporaryDirectory() as other_dir:
        outside_key = Path(other_dir) / "evil_key"
        outside_key.write_text("fake")
        config = SSH_HOST_CONFIG.format(key_path=outside_key.as_posix())
        (tmp_data_root / "config.yaml").write_text(config)

    from portal.app import create_app
    app = create_app()
    client = _inject_admin_session(app)

    _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4022)


def test_ws_rejects_missing_key_file(tmp_data_root, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None

    config = SSH_HOST_CONFIG.format(key_path=(tmp_data_root / "keys" / "absent").as_posix())
    (tmp_data_root / "config.yaml").write_text(config)

    from portal.app import create_app
    app = create_app()
    client = _inject_admin_session(app)

    _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4022)
