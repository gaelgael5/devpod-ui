from __future__ import annotations

import asyncio
import os
import tempfile
import time
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
        # Sans auth_time, session_within_max_age rejette (4001) avant toute validation.
        request.session["auth_time"] = int(time.time())
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


class _ExecSpy:
    """Remplace `create_subprocess_exec` par un vrai process inerte (`sleep`).

    Le pont exige un process qui TIENT le côté slave du PTY (sinon EOF immédiat) ;
    l'écho vient de la discipline de ligne du tty, pas du process. `sleep` couvre
    aussi le précheck (`communicate` sur pipes DEVNULL). Les argv sont capturés
    pour inspecter la commande SSH construite.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.procs: list[asyncio.subprocess.Process] = []
        self._real = asyncio.create_subprocess_exec

    async def __call__(self, *args: object, **kwargs: object) -> asyncio.subprocess.Process:
        self.calls.append([str(a) for a in args])
        spawn_kwargs = {k: v for k, v in kwargs.items() if k in ("stdin", "stdout", "stderr")}
        # Précheck (stdin=DEVNULL, attendu par communicate) → sortie immédiate ;
        # pont PTY → process qui tient le slave sans lire (l'écho vient du tty).
        argv = ("true",) if kwargs.get("stdin") == asyncio.subprocess.DEVNULL else ("sleep", "30")
        proc = await self._real(*argv, **spawn_kwargs)
        self.procs.append(proc)
        return proc


def test_ws_proxy_echoes_data(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les octets envoyés reviennent par l'écho du PTY local (process inerte)."""
    spy = _ExecSpy()

    fd, fake_key_path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    os.close(fd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

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


def test_ws_proxy_opens_tmux_session(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le terminal host tourne dans tmux (session `main` par défaut, `?session=` sinon)."""
    spy = _ExecSpy()

    fd, fake_key_path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    os.close(fd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        patch(
            "portal.routes.ssh_proxy._materialize_system_cert",
            new=AsyncMock(return_value=fake_key_path),
        ),
        admin_client.websocket_connect("/admin/hosts/ssh-dev/ssh?session=ops") as ws,
    ):
        ws.send_bytes(b"x")
        ws.receive_bytes()

    # Dernier subprocess = le pont SSH interactif ; il embarque la commande tmux.
    bridge_cmd = " ".join(spy.calls[-1])
    assert "tmux new-session -A -s ops" in bridge_cmd
    assert "bash -l" in bridge_cmd  # fallback si tmux absent sur le host


def test_ws_proxy_rejects_invalid_session_name(admin_client: TestClient) -> None:
    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg):
        _assert_ws_closes_with(admin_client, "/admin/hosts/ssh-dev/ssh?session=BAD;rm", 4022)


def test_ws_close_kills_subprocess(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fermer le WebSocket tue le subprocess SSH."""
    spy = _ExecSpy()

    fd, fake_key_path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    os.close(fd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    mock_cfg = _make_global_cfg([_SSH_HOST, _DOCKER_HOST])
    with (
        patch("portal.routes.ssh_proxy.load_global", return_value=mock_cfg),
        patch(
            "portal.routes.ssh_proxy._materialize_system_cert",
            new=AsyncMock(return_value=fake_key_path),
        ),
        admin_client.websocket_connect("/admin/hosts/ssh-dev/ssh") as ws,
    ):
        # S'assurer que le pont est établi (écho reçu) avant de fermer :
        # sinon le TestClient annule le handler avant même le spawn du pont.
        ws.send_bytes(b"x")
        ws.receive_bytes()

    # Le pont (dernier process, `sleep` inerte) a été tué au teardown (SIGKILL).
    # Le teardown du handler s'achève après la sortie du `with` → courte attente.
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(spy.procs) >= 2 and spy.procs[-1].returncode is not None:
            break
        time.sleep(0.05)
    assert len(spy.procs) >= 2, "Le pont SSH doit avoir été lancé"
    assert spy.procs[-1].returncode == -9, "Le subprocess doit être killed après fermeture WS"
