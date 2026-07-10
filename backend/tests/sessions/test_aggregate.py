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


def _refs(*items: tuple[str, str, str]) -> Any:
    """Fabrique un stub `list_workspace_refs` renvoyant les refs données.

    Chaque item = (login, name, host). `login=None` (vue admin) ou un login précis
    sont ignorés par le stub : il renvoie toujours la liste fournie.
    """

    async def _stub(login: str | None, conn: Any) -> list[dict[str, Any]]:
        return [{"login": lg, "name": nm, "host": ho} for lg, nm, ho in items]

    return _stub


def _statuses(*rows: dict[str, Any]) -> Any:
    async def _stub(*args: Any, **kw: Any) -> list[dict[str, Any]]:
        return list(rows)

    return _stub


@pytest.mark.asyncio
async def test_user_lists_own_running_tmux_sessions(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\nbuild\n"

    monkeypatch.setattr(
        aggregate, "list_workspace_refs", _refs(("alice", "ws", ""), ("alice", "old", ""))
    )
    monkeypatch.setattr(
        aggregate,
        "list_by_login_db",
        _statuses(
            {"ws_id": "alice-ws", "login": "alice", "status": "running"},
            {"ws_id": "alice-old", "login": "alice", "status": "stopped"},
        ),
    )
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)

    # Seul le workspace running est sondé ; le stopped est ignoré (pas de bruit).
    ws = [r for r in result if r["family"] == "workspace"]
    assert {r["session"] for r in ws} == {"main", "build"}
    assert all(r["target"] == "alice-ws" for r in ws)
    assert all(r["owner"] == "alice" for r in ws)
    assert all(r["orphan"] is False for r in ws)  # running ⇒ pas orphelin
    assert not [r for r in result if r["family"] == "host"]
    # Pré-chauffe uniquement du running.
    await asyncio.sleep(0)
    assert patch_common == ["alice-ws"]


@pytest.mark.asyncio
async def test_live_session_under_non_running_is_orphan(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    """Cas `workflow` : déclaré, sans ligne de statut running, mais tmux vivant."""

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "workflow1\n"

    monkeypatch.setattr(
        aggregate, "list_workspace_refs", _refs(("admin", "workflow", "host-dev-01"))
    )
    # Aucune ligne workspace_status → statut « unknown ».
    monkeypatch.setattr(aggregate, "list_by_login_db", _statuses())
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="admin", is_admin=False)
    ws = [r for r in result if r["family"] == "workspace"]
    assert len(ws) == 1
    assert ws[0]["session"] == "workflow1"
    assert ws[0]["orphan"] is True
    assert ws[0]["host"] == "host-dev-01"  # nœud tiré de la config faute de statut
    # Un `unknown` n'est PAS pré-chauffé (tunnel voué à échouer si down).
    await asyncio.sleep(0)
    assert patch_common == []


@pytest.mark.asyncio
async def test_stopped_workspace_is_not_probed(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    probed: list[str] = []

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        probed.append(ws_id)
        return 0, "main\n"

    monkeypatch.setattr(aggregate, "list_workspace_refs", _refs(("alice", "gone", "")))
    monkeypatch.setattr(
        aggregate,
        "list_by_login_db",
        _statuses({"ws_id": "alice-gone", "login": "alice", "status": "stopped"}),
    )
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)
    assert [r for r in result if r["family"] == "workspace"] == []
    assert probed == []  # aucune sonde SSH sur un workspace arrêté


@pytest.mark.asyncio
async def test_unreachable_running_marked_but_unknown_skipped(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        raise RuntimeError("ssh boom")

    monkeypatch.setattr(
        aggregate, "list_workspace_refs", _refs(("alice", "run", ""), ("alice", "maybe", ""))
    )
    monkeypatch.setattr(
        aggregate,
        "list_by_login_db",
        _statuses({"ws_id": "alice-run", "login": "alice", "status": "running"}),
    )
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)
    run = [r for r in result if r["target"] == "alice-run"]
    maybe = [r for r in result if r["target"] == "alice-maybe"]
    # running injoignable ⇒ marqueur unreachable ; unknown injoignable ⇒ silencieux.
    assert len(run) == 1 and run[0]["unreachable"] is True and run[0]["session"] is None
    assert maybe == []


@pytest.mark.asyncio
async def test_entries_carry_host_of_the_node(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    """Chaque session porte le `host` (nœud) où elle tourne, pour un regroupement."""

    async def _all_tests(conn: Any):
        return [("bob", "bob-ws", "testvm-1", "test1")]

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\n"

    class _Host:
        def __init__(self, name: str, type: str) -> None:
            self.name = name
            self.type = type

    class _Cfg:
        hosts = [_Host("node1", "ssh")]

    monkeypatch.setattr(aggregate, "list_workspace_refs", _refs(("alice", "ws", "node2")))
    monkeypatch.setattr(
        aggregate,
        "list_all_status_db",
        _statuses(
            {"ws_id": "alice-ws", "login": "alice", "status": "running", "host_name": "node2"}
        ),
    )
    monkeypatch.setattr(aggregate, "list_all_test_hosts", _all_tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    monkeypatch.setattr("portal.config.store.load_global", lambda: _Cfg())

    result = await aggregate.list_sessions(login="admin", is_admin=True)
    by = {(r["family"], r["target"]): r for r in result}

    assert by[("workspace", "alice-ws")]["host"] == "node2"
    assert by[("host", "node1")]["host"] == "node1"
    assert by[("test", "testvm-1")]["host"] == "testvm-1"


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

    async def _tests(login: str, conn: Any):
        return []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return 0, "main\nother\n"

    monkeypatch.setattr(aggregate, "list_workspace_refs", _refs(("alice", "ws", "")))
    monkeypatch.setattr(
        aggregate,
        "list_by_login_db",
        _statuses({"ws_id": "alice-ws", "login": "alice", "status": "running"}),
    )
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)

    result = await aggregate.list_sessions(login="alice", is_admin=False)
    by_session = {r["session"]: r for r in result if r["family"] == "workspace"}
    assert by_session["main"]["attached"] is True
    assert by_session["other"]["attached"] is False


@pytest.mark.asyncio
async def test_admin_includes_all_ws_hosts_and_tests(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
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

    monkeypatch.setattr(
        aggregate, "list_workspace_refs", _refs(("alice", "ws", ""), ("bob", "ws", ""))
    )
    monkeypatch.setattr(
        aggregate,
        "list_all_status_db",
        _statuses(
            {"ws_id": "alice-ws", "login": "alice", "status": "running"},
            {"ws_id": "bob-ws", "login": "bob", "status": "running"},
        ),
    )
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
