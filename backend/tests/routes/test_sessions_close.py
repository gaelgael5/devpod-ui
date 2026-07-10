from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request

from portal.sessions import registry
from portal.sessions.registry import LiveTerminal

from .test_workspace_ssh import BASE_CONFIG


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


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
    r = APIRouter()

    @r.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": login, "roles": session_roles}
        request.session["auth_time"] = int(time.time())
        return {"ok": True}

    app.include_router(r)
    client = TestClient(app)
    client.post("/_test/login")
    return client


def _register(family: registry.Family, target: str, owner: str, session=None):
    """Enregistre un terminal vivant avec un closer traçable ; renvoie la liste témoin."""
    calls: list[str] = []
    term = LiveTerminal(
        id=f"{family}-{target}-{session}", family=family, target=target, owner=owner,
        session=session, since=1.0,
    )
    registry.register(term, closer=lambda: calls.append(term.id))
    return calls


def test_close_host_detaches_live_terminal(tmp_path, monkeypatch):
    """Un admin ferme un terminal host : le closer est invoqué, 204."""
    calls = _register("host", "node1", "admin")
    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])
    resp = client.post(
        "/sessions/close",
        json={"family": "host", "target": "node1", "owner": "admin", "session": None},
    )
    assert resp.status_code == 204
    assert calls == ["host-node1-None"]


def test_close_test_vm_detaches_own_terminal(tmp_path, monkeypatch):
    calls = _register("test", "node-vm", "alice")
    client = _make_client(tmp_path, monkeypatch, login="alice", roles=["dev"])
    resp = client.post(
        "/sessions/close",
        json={"family": "test", "target": "node-vm", "owner": "alice", "session": None},
    )
    assert resp.status_code == 204
    assert calls == ["test-node-vm-None"]


def test_close_other_owner_denied_for_non_admin(tmp_path, monkeypatch):
    calls = _register("test", "node-vm", "bob")
    client = _make_client(tmp_path, monkeypatch, login="alice", roles=["dev"])
    resp = client.post(
        "/sessions/close",
        json={"family": "test", "target": "node-vm", "owner": "bob", "session": None},
    )
    assert resp.status_code == 403
    assert calls == []  # closer jamais invoqué


def test_close_invalid_owner_rejected(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])
    resp = client.post(
        "/sessions/close",
        json={"family": "test", "target": "node-vm", "owner": "bad!name", "session": None},
    )
    assert resp.status_code == 422


def test_close_workspace_kills_tmux_and_detaches(tmp_path, monkeypatch):
    calls = _register("workspace", "alice-proj", "alice", "main")

    killed: list[tuple[str, str]] = []

    async def _fake_ws_exec(login, ws_id, command, timeout=30.0):
        killed.append((ws_id, command))
        return 0, ""

    async def _fake_emit(*a, **k):
        return None

    monkeypatch.setattr("portal.sessions.close_ops.ws_exec", _fake_ws_exec)
    monkeypatch.setattr("portal.sessions.close_ops.emit_event", _fake_emit)

    client = _make_client(tmp_path, monkeypatch, login="alice", roles=["dev"])
    resp = client.post(
        "/sessions/close",
        json={"family": "workspace", "target": "alice-proj", "owner": "alice", "session": "main"},
    )
    assert resp.status_code == 204
    assert calls == ["workspace-alice-proj-main"]  # pont détaché
    assert killed and killed[0][0] == "alice-proj"
    assert "kill-session -t main" in killed[0][1]


def test_close_admin_can_kill_other_user_workspace_tmux(tmp_path, monkeypatch):
    """Décision produit : l'admin peut fermer (et tuer tmux) le workspace d'un autre user."""
    killed: list[str] = []

    async def _fake_ws_exec(login, ws_id, command, timeout=30.0):
        killed.append(ws_id)
        return 0, ""

    async def _fake_emit(*a, **k):
        return None

    monkeypatch.setattr("portal.sessions.close_ops.ws_exec", _fake_ws_exec)
    monkeypatch.setattr("portal.sessions.close_ops.emit_event", _fake_emit)

    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])
    resp = client.post(
        "/sessions/close",
        json={"family": "workspace", "target": "bob-proj", "owner": "bob", "session": "main"},
    )
    assert resp.status_code == 204
    assert killed == ["bob-proj"]


def test_close_workspace_target_owner_mismatch_rejected(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, login="root", roles=["dev", "admin"])
    resp = client.post(
        "/sessions/close",
        # target ne commence pas par "bob-" → incohérence détectée
        json={"family": "workspace", "target": "alice-proj", "owner": "bob", "session": "main"},
    )
    assert resp.status_code == 422
