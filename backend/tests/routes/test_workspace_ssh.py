# backend/tests/routes/test_workspace_ssh.py
from __future__ import annotations

import asyncio
import base64
import json as _json
import time
from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

BASE_CONFIG = {
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
        "client_cert_path": "/data/certs/portal",
    },
    "hosts": [],
    "caddy": {"admin_api": ""},
    "cloudflare_manager": {"url": "", "api_key": ""},
}


def _make_client(
    tmp_path: Path, monkeypatch, login: str = "alice", roles: list[str] | None = None
) -> TestClient:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    session_roles = roles if roles is not None else ["dev"]

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": login, "roles": session_roles}
        request.session["auth_time"] = int(time.time())
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    return client


def _write_start_recipe(
    data_root: Path, recipe_id: str, scope: str = "shared", login: str = "alice"
) -> None:
    if scope == "shared":
        recipe_dir = data_root / "recipes" / recipe_id
    else:
        recipe_dir = data_root / "users" / login / "recipes" / recipe_id
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": recipe_id, "type": "start", "description": "test"}), encoding="utf-8"
    )
    (recipe_dir / "start.sh").write_text(
        f"#!/usr/bin/env bash\nexec {recipe_id}\n", encoding="utf-8"
    )


def _assert_ws_closes_with(client: TestClient, path: str, expected_code: int) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(path) as ws:
        ws.receive_text()
    assert exc_info.value.code == expected_code


# ── Tests d'authentification ──────────────────────────────────────────────────

def test_ws_workspace_ssh_rejects_unauthenticated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    from portal.app import create_app
    client = TestClient(create_app())
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh", 4001)


# ── Tests de validation ────────────────────────────────────────────────────────

def test_ws_workspace_ssh_rejects_invalid_workspace_name(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    _assert_ws_closes_with(client, "/me/workspaces/INVALID!/ssh", 4022)


def test_ws_workspace_ssh_rejects_unknown_start_recipe(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?start=unknown-recipe", 4022)


def test_ws_workspace_ssh_rejects_start_recipe_wrong_type(tmp_path: Path, monkeypatch) -> None:
    """Une recette de type install ne peut pas être utilisée comme start recipe."""
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod
    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    install_dir = tmp_path / "recipes" / "my-install"
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "my-install", "type": "install"}), encoding="utf-8"
    )
    (install_dir / "devcontainer-feature.json").write_text(
        _json.dumps({"id": "my-install", "version": "1.0.0"}), encoding="utf-8"
    )
    (install_dir / "install.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        request.session["auth_time"] = int(time.time())
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?start=my-install", 4022)


# ── Tests proxy nominal ────────────────────────────────────────────────────────

class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = _FakeStdin(self)
        self.stdout = _FakeStdout()

    def kill(self) -> None:
        self.returncode = -9
        self.stdout._close()

    async def wait(self) -> int:
        return self.returncode or 0


class _FakeStdin:
    def __init__(self, proc: _FakeProcess) -> None:
        self._proc = proc

    def is_closing(self) -> bool:
        return self._proc.returncode is not None

    def write(self, data: bytes) -> None:
        pass

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
        self._queue.put_nowait(b"")

    async def read(self, n: int) -> bytes:
        if self._closed and self._queue.empty():
            return b""
        return await self._queue.get()


def test_ws_workspace_ssh_no_start_uses_tmux_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans ?start, la commande doit utiliser 'tmux new -A -s main'."""
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch)

    with client.websocket_connect("/me/workspaces/my-ws/ssh"):
        pass

    assert captured, "create_subprocess_exec doit avoir été appelé"
    cmd = captured[0]
    assert "ssh" in cmd
    assert any("alice-my-ws" in s for s in cmd)
    command_str = cmd[-1]
    # Le socket tmux est détecté dynamiquement (TMUX_SOCK) puis `new -A -s main`.
    assert "new -A -s main" in command_str
    assert "base64" not in command_str


def test_ws_workspace_ssh_with_start_encodes_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avec ?start=claude-rc, start.sh est encodé en base64 dans la commande."""
    _write_start_recipe(tmp_path, "claude-rc")
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch)

    with client.websocket_connect("/me/workspaces/my-ws/ssh?start=claude-rc"):
        pass

    assert captured
    cmd = captured[0]
    command_str = cmd[-1]
    assert "base64" in command_str
    assert "tmux new -A -s claude-rc" in command_str

    import re as _re
    match = _re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", command_str)
    assert match, "La commande doit contenir un bloc base64"
    decoded = base64.b64decode(match.group(1)).decode()
    assert "exec claude-rc" in decoded


def test_ws_workspace_ssh_admin_can_target_other_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un admin qui passe ?owner=bob cible le conteneur bob-my-ws, pas le sien."""
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])

    with client.websocket_connect("/me/workspaces/my-ws/ssh?owner=bob"):
        pass

    assert captured
    cmd = captured[0]
    assert any("bob-my-ws" in s for s in cmd)
    assert not any("root-my-ws" in s for s in cmd)


def test_ws_workspace_ssh_non_admin_owner_denied(tmp_path: Path, monkeypatch) -> None:
    """Un non-admin qui passe ?owner=bob est refusé (4001)."""
    client = _make_client(tmp_path, monkeypatch, login="alice", roles=["dev"])
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?owner=bob", 4001)


def test_ws_workspace_ssh_owner_equals_login_allowed_for_non_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?owner=<soi-même> reste autorisé sans privilège (cas nominal)."""
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch, login="alice", roles=["dev"])

    with client.websocket_connect("/me/workspaces/my-ws/ssh?owner=alice"):
        pass

    assert captured
    assert any("alice-my-ws" in s for s in captured[0])


def test_ws_workspace_ssh_admin_invalid_owner_rejected(tmp_path: Path, monkeypatch) -> None:
    """Un owner non conforme (login invalide) est rejeté (4022) même pour un admin."""
    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?owner=bad!name", 4022)


def test_ws_workspace_ssh_origin_rejected_non_dev(tmp_path: Path, monkeypatch) -> None:
    """En mode non-dev, un mauvais Origin est rejeté (4003)."""
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    import portal.settings as mod
    mod._settings = None
    cfg = dict(BASE_CONFIG)
    cfg["server"] = dict(cfg["server"])
    cfg["server"]["dev_mode"] = False
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg), encoding="utf-8")

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        request.session["auth_time"] = int(time.time())
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/me/workspaces/my-ws/ssh",
            headers={"Origin": "https://evil.example.com"},
        ) as ws,
    ):
        ws.receive_text()
    assert exc_info.value.code == 4003
