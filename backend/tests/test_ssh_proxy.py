from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from portal.config.models import HostConfig


def _make_global_cfg(hosts: list[HostConfig]) -> MagicMock:
    """Construit un mock de GlobalConfig avec les hosts donnés."""
    cfg = MagicMock()
    cfg.hosts = hosts
    cfg.server.external_url = "https://dev.yoops.org"
    return cfg


_SSH_HOST = HostConfig(
    name="ssh-dev",
    type="ssh",
    address="debian@192.168.10.175",
    host_cert_slug="pve1-ssh-key",
)
_DOCKER_HOST = HostConfig(
    name="docker-local",
    type="docker-tls",
    docker_host="tcp://192.168.1.50:2376",
)


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


def _assert_ws_closes_with(client: TestClient, path: str, expected_code: int) -> None:
    """Connecte en WebSocket, tente de lire, vérifie le code de fermeture."""
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(path) as ws:
        ws.receive_text()
    assert exc_info.value.code == expected_code


@pytest.fixture
def tmp_data_root_ssh(tmp_data_root: Path, monkeypatch) -> Path:
    """Data root avec DEV_MODE=true et settings réinitialisés."""
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod

    mod._settings = None
    return tmp_data_root


@pytest.fixture
def admin_client(tmp_data_root_ssh: Path) -> TestClient:
    """TestClient admin avec load_global mocké (hosts SSH + docker)."""
    from portal.app import create_app

    app = create_app()
    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        return _inject_admin_session(app)


# ── Tests d'authentification ──────────────────────────────────────────────────


def test_ws_rejects_unauthenticated(tmp_data_root_ssh: Path) -> None:
    from portal.app import create_app

    app = create_app()
    client = TestClient(app)  # pas de login → pas de session
    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4001)


def test_ws_rejects_non_admin(tmp_data_root_ssh: Path) -> None:
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

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(client, "/admin/hosts/ssh-dev/ssh", 4001)


# ── Tests de validation de la config ─────────────────────────────────────────


def test_ws_rejects_unknown_host(admin_client: TestClient) -> None:
    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(admin_client, "/admin/hosts/inexistant/ssh", 4004)


def test_ws_rejects_docker_tls_host(admin_client: TestClient) -> None:
    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(admin_client, "/admin/hosts/docker-local/ssh", 4022)


def test_ws_rejects_empty_cert_slug(admin_client: TestClient) -> None:
    """Ferme avec 4022 si host_cert_slug est vide."""
    empty_slug_host = HostConfig(
        name="ssh-dev",
        type="ssh",
        address="debian@192.168.10.175",
        host_cert_slug="",  # pas encore bootstrappé
    )
    mock_cfg = _make_global_cfg([empty_slug_host, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(admin_client, "/admin/hosts/ssh-dev/ssh", 4022)


def test_ws_rejects_cert_not_found_in_harpo(admin_client: TestClient) -> None:
    """Ferme le WebSocket si la clé n'est pas trouvée dans harpo."""
    missing_slug_host = HostConfig(
        name="ssh-dev",
        type="ssh",
        address="debian@192.168.10.175",
        host_cert_slug="missing-slug",
    )
    mock_cfg = _make_global_cfg([missing_slug_host, _DOCKER_HOST])
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        patch(
            "portal.routes.ssh_proxy._materialize_system_cert",
            new=AsyncMock(side_effect=KeyError("missing-slug")),
        ),
    ):
        _assert_ws_closes_with(admin_client, "/admin/hosts/ssh-dev/ssh", 4022)


def test_ws_rejects_bad_origin(tmp_data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejette une connexion WebSocket avec un Origin non autorisé (anti-CSWSH)."""
    import portal.settings as mod

    monkeypatch.setattr(mod, "_settings", None)
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret-for-cswsh")
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("PORTAL_VAULT_KEK", "a" * 64)  # clé factice 32 octets hex

    from portal.app import create_app

    app = create_app()
    client = _inject_admin_session(app)

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    mock_cfg.server.external_url = "https://dev.yoops.org"
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/admin/hosts/ssh-dev/ssh",
            headers={"Origin": "https://evil.example.com"},
        ) as ws,
    ):
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


def test_ws_proxy_echoes_data(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le subprocess SSH factice (echo) remet les bytes sur le WebSocket."""
    fake_proc = _FakeProcess(echo=True)

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return fake_proc

    fd, fake_key_path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    os.close(fd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        patch(
            "portal.routes.ssh_proxy._materialize_system_cert",
            new=AsyncMock(return_value=fake_key_path),
        ),
        admin_client.websocket_connect("/admin/hosts/ssh-dev/ssh") as ws,
    ):
        ws.send_bytes(b"hello")
        data = ws.receive_bytes()
        assert data == b"hello"


def test_ws_close_kills_subprocess(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fermer le WebSocket tue le subprocess SSH."""
    fake_proc = _FakeProcess(echo=False)

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return fake_proc

    fd, fake_key_path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    os.close(fd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        patch(
            "portal.routes.ssh_proxy._materialize_system_cert",
            new=AsyncMock(return_value=fake_key_path),
        ),
        admin_client.websocket_connect("/admin/hosts/ssh-dev/ssh"),
    ):
        pass  # ferme immédiatement le WS

    assert fake_proc._killed, "Le subprocess doit être killed après fermeture WS"
