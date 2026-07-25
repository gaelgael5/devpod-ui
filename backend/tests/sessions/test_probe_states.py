"""Différenciation « workspace injoignable » vs « aucune session tmux » (bug 807fed1c).

Contrats :
- rc 0  → sessions listées ;
- rc 1/127 (pas de serveur tmux / tmux absent) → joignable, zéro session — état normal ;
- rc 255 (transport SSH) ou TIMEOUT_RC (timeout ws_exec) → workspace injoignable.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from portal.devpod import exec as dexec
from portal.sessions import aggregate, registry


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    registry.clear()
    aggregate.clear_sessions_cache()
    yield
    registry.clear()
    aggregate.clear_sessions_cache()


class _FakeEngine:
    @contextlib.asynccontextmanager
    async def connect(self):
        yield object()


@pytest.fixture
def patch_common(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(aggregate, "_get_engine", lambda: _FakeEngine())

    async def _fake_warm(login: str, ws_id: str, **kw: Any) -> bool:
        return True

    monkeypatch.setattr(aggregate, "warm_tunnel", _fake_warm)


def _refs(*items: tuple[str, str, str]) -> Any:
    async def _stub(login: str | None, conn: Any) -> list[dict[str, Any]]:
        return [{"login": lg, "name": nm, "host": ho} for lg, nm, ho in items]

    return _stub


def _statuses(*rows: dict[str, Any]) -> Any:
    async def _stub(*args: Any, **kw: Any) -> list[dict[str, Any]]:
        return list(rows)

    return _stub


async def _no_tests(login: str, conn: Any):
    return []


def _setup(monkeypatch: pytest.MonkeyPatch, rc: int, output: str = "") -> None:
    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        return rc, output

    monkeypatch.setattr(aggregate, "list_workspace_refs", _refs(("alice", "ws", "node1")))
    monkeypatch.setattr(
        aggregate,
        "list_by_login_db",
        _statuses({"ws_id": "alice-ws", "login": "alice", "status": "running"}),
    )
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _no_tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)


# ─── ws_exec : rc de timeout distinct ─────────────────────────────────────────


def test_timeout_rc_is_distinct_from_tmux_and_ssh_codes() -> None:
    # 1 = tmux sans serveur, 127 = commande absente, 255 = transport ssh.
    assert dexec.TIMEOUT_RC not in (0, 1, 127, 255)


@pytest.mark.asyncio
async def test_ws_exec_timeout_returns_timeout_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        def kill(self) -> None:
            pass

        async def wait(self) -> int:
            return -9

        async def communicate(self) -> tuple[bytes, bytes]:  # pragma: no cover - jamais fini
            await asyncio.sleep(3600)
            return b"", b""

    async def _fake_exec(*args: Any, **kw: Any) -> _Proc:
        return _Proc()

    monkeypatch.setattr(dexec.asyncio, "create_subprocess_exec", _fake_exec)

    async def _fake_wait_for(coro: Any, timeout: float) -> Any:
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(dexec.asyncio, "wait_for", _fake_wait_for)

    rc, output = await dexec.ws_exec("alice", "alice-ws", "true", timeout=0.01)
    assert rc == dexec.TIMEOUT_RC
    # Le libellé est un contrat : create_session le détecte par sous-chaîne.
    assert "timed out" in output


# ─── agrégat : classification des rc de sonde ─────────────────────────────────


@pytest.mark.asyncio
async def test_no_tmux_server_is_reachable_not_unreachable(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    """rc=1 (aucun serveur tmux) = état normal : PAS de marqueur unreachable."""
    _setup(monkeypatch, rc=1)
    result = await aggregate.list_sessions(login="alice", is_admin=False)
    assert [r for r in result if r["family"] == "workspace"] == []


@pytest.mark.asyncio
async def test_tmux_missing_is_reachable_not_unreachable(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    """rc=127 (tmux non installé) : joignable, zéro session — pas d'erreur."""
    _setup(monkeypatch, rc=127)
    result = await aggregate.list_sessions(login="alice", is_admin=False)
    assert [r for r in result if r["family"] == "workspace"] == []


@pytest.mark.asyncio
async def test_ssh_transport_failure_marks_unreachable(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    _setup(monkeypatch, rc=255)
    result = await aggregate.list_sessions(login="alice", is_admin=False)
    ws = [r for r in result if r["family"] == "workspace"]
    assert len(ws) == 1
    assert ws[0]["unreachable"] is True
    assert ws[0]["host"] == "node1"


@pytest.mark.asyncio
async def test_probe_timeout_marks_unreachable(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    _setup(monkeypatch, rc=dexec.TIMEOUT_RC, output="SSH command timed out")
    result = await aggregate.list_sessions(login="alice", is_admin=False)
    ws = [r for r in result if r["family"] == "workspace"]
    assert len(ws) == 1
    assert ws[0]["unreachable"] is True


@pytest.mark.asyncio
async def test_probe_command_does_not_mask_tmux_rc(
    monkeypatch: pytest.MonkeyPatch, patch_common
) -> None:
    """La sonde ne doit plus terminer par `|| true` : le rc de tmux EST le signal."""
    seen: list[str] = []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        seen.append(command)
        return 0, ""

    _setup(monkeypatch, rc=0)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    await aggregate.list_sessions(login="alice", is_admin=False)
    assert seen and "|| true" not in seen[0]
