from __future__ import annotations

import asyncio
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


def test_ws_rejects_bad_origin(tmp_data_root, monkeypatch):
    """Rejette une connexion WebSocket avec un Origin non autorisé (anti-CSWSH)."""
    import portal.settings as mod
    monkeypatch.setattr(mod, "_settings", None)
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret-for-cswsh")
    monkeypatch.setenv("DEV_MODE", "false")

    key_dir = tmp_data_root / "keys" / "hosts"
    key_dir.mkdir(parents=True)
    key_file = key_dir / "ssh_dev_ed25519"
    key_file.write_text("fake key")
    key_file.chmod(0o600)
    config = SSH_HOST_CONFIG.format(key_path=key_file.as_posix())
    (tmp_data_root / "config.yaml").write_text(config)

    from portal.app import create_app
    app = create_app()
    client = _inject_admin_session(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, \
         client.websocket_connect(
             "/admin/hosts/ssh-dev/ssh",
             headers={"Origin": "https://evil.example.com"},
         ) as ws:
        ws.receive_text()
    assert exc_info.value.code == 4003


# ── Tests du proxy nominal ────────────────────────────────────────────────────


class _FakeProcess:
    """Simule asyncio.subprocess.Process pour les tests proxy."""

    def __init__(self, echo: bool = True) -> None:
        self.returncode: int | None = None
        self._killed = False
        self._echo = echo
        self.stdin = _FakeStdin(self)
        self.stdout = _FakeStdout()

    def kill(self) -> None:
        self._killed = True
        self.returncode = -9
        # Débloquer le lecteur stdout (envoyer EOF)
        self.stdout._close()

    async def wait(self) -> int:
        return self.returncode or 0


class _FakeStdin:
    def __init__(self, proc: _FakeProcess) -> None:
        self._proc = proc

    def is_closing(self) -> bool:
        return self._proc.returncode is not None

    def write(self, data: bytes) -> None:
        if self._proc._echo:
            self._proc.stdout._feed(data)

    async def drain(self) -> None:
        pass


class _FakeStdout:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    def _feed(self, data: bytes) -> None:
        self._queue.put_nowait(data)

    def _close(self) -> None:
        self._closed = True
        self._queue.put_nowait(b"")  # sentinelle EOF

    async def read(self, n: int) -> bytes:
        if self._closed and self._queue.empty():
            return b""
        chunk = await self._queue.get()
        return chunk


def test_ws_proxy_echoes_data(data_root_with_ssh: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le subprocess SSH factice (echo) remet les bytes sur le WebSocket."""
    fake_proc = _FakeProcess(echo=True)

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    client = _make_client(data_root_with_ssh)
    with client.websocket_connect("/admin/hosts/ssh-dev/ssh") as ws:
        ws.send_bytes(b"hello")
        data = ws.receive_bytes()
        assert data == b"hello"


def test_ws_close_kills_subprocess(
    data_root_with_ssh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fermer le WebSocket tue le subprocess SSH."""
    fake_proc = _FakeProcess(echo=False)

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    client = _make_client(data_root_with_ssh)
    with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
        pass  # ferme immédiatement le WS

    assert fake_proc._killed, "Le subprocess doit être killed après fermeture WS"
