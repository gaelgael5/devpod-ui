from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from portal.sessions import aggregate, registry
from portal.sessions.registry import LiveTerminal


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    registry.clear()
    yield
    registry.clear()


class _FakeEngine:
    """Engine minimal : `.connect()` renvoie un CM async yieldant un sentinel."""

    @contextlib.asynccontextmanager
    async def connect(self):
        yield object()


@pytest.fixture
def patch_common(monkeypatch: pytest.MonkeyPatch):
    """Patche l'engine + warm_tunnel (no-op) ; renvoie un compteur d'appels warm."""
    monkeypatch.setattr(aggregate, "_get_engine", lambda: _FakeEngine())
    warmed: list[str] = []

    async def _fake_warm(login: str, ws_id: str, **kw: Any) -> bool:
        warmed.append(ws_id)
        return True

    monkeypatch.setattr(aggregate, "warm_tunnel", _fake_warm)
    return warmed


@pytest.mark.asyncio
async def test_user_lists_own_running_tmux_sessions(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    async def _by_login(login: str, conn: Any) -> list[dict[str, Any]]:
        assert login == "alice"
        return [
            {"ws_id": "alice-ws", "login": "alice", "status": "running"},
            {"ws_id": "alice-old", "login": "alice", "status": "stopped"},
        ]

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\nbuild\n"

    monkeypatch.setattr(aggregate, "list_by_login_db", _by_login)
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)

    # Seul le workspace running est énuméré ; 2 sessions tmux.
    ws = [r for r in result if r["family"] == "workspace"]
    assert {r["session"] for r in ws} == {"main", "build"}
    assert all(r["target"] == "alice-ws" for r in ws)
    assert all(r["owner"] == "alice" for r in ws)
    # Pas de hosts en vue user.
    assert not [r for r in result if r["family"] == "host"]
    # Pré-chauffe fire-and-forget : la tâche create_task ne s'exécute qu'au
    # prochain point de yield → on cède la main puis on vérifie.
    await asyncio.sleep(0)
    assert patch_common == ["alice-ws"]


@pytest.mark.asyncio
async def test_attached_flag_from_registry(monkeypatch: pytest.MonkeyPatch, patch_common) -> None:
    registry.register(
        LiveTerminal(
            id="x",
            family="workspace",
            target="alice-ws",
            owner="alice",
            session="main",
            since=1.0,
        )
    )

    async def _by_login(login: str, conn: Any):
        return [{"ws_id": "alice-ws", "login": "alice", "status": "running"}]

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\nother\n"

    monkeypatch.setattr(aggregate, "list_by_login_db", _by_login)
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)
    by_session = {r["session"]: r for r in result if r["family"] == "workspace"}
    assert by_session["main"]["attached"] is True
    assert by_session["other"]["attached"] is False


@pytest.mark.asyncio
async def test_unreachable_workspace_does_not_abort(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    async def _by_login(login: str, conn: Any):
        return [
            {"ws_id": "alice-a", "login": "alice", "status": "running"},
            {"ws_id": "alice-b", "login": "alice", "status": "running"},
        ]

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        if ws_id == "alice-a":
            raise RuntimeError("ssh boom")
        return 0, "main\n"

    monkeypatch.setattr(aggregate, "list_by_login_db", _by_login)
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)
    a = [r for r in result if r["target"] == "alice-a"]
    b = [r for r in result if r["target"] == "alice-b"]
    assert len(a) == 1 and a[0]["unreachable"] is True and a[0]["session"] is None
    assert {r["session"] for r in b} == {"main"}


@pytest.mark.asyncio
async def test_admin_includes_all_ws_hosts_and_tests(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    async def _running(conn: Any):
        return [
            {"ws_id": "alice-ws", "login": "alice", "status": "running"},
            {"ws_id": "bob-ws", "login": "bob", "status": "running"},
        ]

    async def _all_tests(conn: Any):
        return [("bob", "bob-ws", "testvm-1", "test1")]

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\n"

    class _Host:
        def __init__(self, name: str, type: str) -> None:
            self.name = name
            self.type = type

    class _Cfg:
        hosts = [_Host("node1", "ssh"), _Host("dockerhost", "docker-tls")]

    monkeypatch.setattr(aggregate, "list_running_db", _running)
    monkeypatch.setattr(aggregate, "list_all_test_hosts", _all_tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    monkeypatch.setattr("portal.config.store.load_global", lambda: _Cfg())

    result = await aggregate.list_sessions(login="admin", is_admin=True)

    ws_owners = {r["owner"] for r in result if r["family"] == "workspace"}
    assert ws_owners == {"alice", "bob"}
    hosts = [r for r in result if r["family"] == "host"]
    assert {r["target"] for r in hosts} == {"node1"}  # docker-tls exclu
    tests = [r for r in result if r["family"] == "test"]
    assert len(tests) == 1
    assert tests[0]["target"] == "testvm-1"
    assert tests[0]["owner"] == "bob"
    assert tests[0]["workspace"] == "bob-ws"
