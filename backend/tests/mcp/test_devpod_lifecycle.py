# backend/tests/mcp/test_devpod_lifecycle.py
"""Impls workspace_start / stop / restart — modèle async operations_* (spec 25)."""
from __future__ import annotations

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_stop_launches_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_launch(kind: str, workspace: str, owner_login: str, work: object) -> str:
        captured.update(kind=kind, workspace=workspace, owner=owner_login)
        return "d" * 32

    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)
    res = await devpod_tools._workspace_stop(None, {"workspace": "dev"}, "admin")
    assert res == {"operation_id": "d" * 32}
    assert captured == {"kind": "workspace_stop", "workspace": "dev", "owner": "admin"}


@pytest.mark.asyncio
async def test_start_launches_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_launch(kind: str, workspace: str, owner_login: str, work: object) -> str:
        captured.update(kind=kind, workspace=workspace, owner=owner_login)
        return "e" * 32

    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)
    res = await devpod_tools._workspace_start(None, {"workspace": "dev"}, "admin")
    assert res == {"operation_id": "e" * 32}
    assert captured == {"kind": "workspace_start", "workspace": "dev", "owner": "admin"}


@pytest.mark.asyncio
async def test_restart_launches_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_launch(kind: str, workspace: str, owner_login: str, work: object) -> str:
        captured.update(kind=kind, workspace=workspace, owner=owner_login)
        return "f" * 32

    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)
    res = await devpod_tools._workspace_restart(None, {"workspace": "dev"}, "admin")
    assert res == {"operation_id": "f" * 32}
    assert captured == {"kind": "workspace_restart", "workspace": "dev", "owner": "admin"}


@pytest.mark.asyncio
async def test_restart_work_stops_then_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vérifie que restart.work() appelle stop AVANT _start_existing (invariant C1)."""
    import portal.db.engine as _engine_mod

    # ── 1. capture le coroutine work via fake launch_operation ─────────────
    work_holder: dict[str, object] = {}

    def fake_launch(kind: str, workspace: str, owner_login: str, work: object) -> str:
        work_holder["work"] = work
        return "a" * 32

    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)

    # ── 2. enregistreur d'ordre ────────────────────────────────────────────
    order: list[str] = []

    # ── 3. fake get_service().stop ─────────────────────────────────────────
    class FakeService:
        async def stop(self, *args: object) -> None:
            order.append("stop")

    monkeypatch.setattr(devpod_tools, "get_service", lambda: FakeService())

    # ── 4. fake _start_existing ────────────────────────────────────────────
    async def fake_start_existing(login: str, name: str, conn: object) -> str:
        order.append("start")
        return f"{login}-{name}"

    monkeypatch.setattr(devpod_tools, "_start_existing", fake_start_existing)

    # ── 5. fake _get_engine (async context manager pour .begin()) ──────────
    class _FakeBeginner:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            pass

    class _FakeEngine:
        def begin(self) -> _FakeBeginner:
            return _FakeBeginner()

    monkeypatch.setattr(_engine_mod, "_get_engine", lambda: _FakeEngine())

    # ── 6. déclenche la création du work (sans l'exécuter) ────────────────
    res = await devpod_tools._workspace_restart(None, {"workspace": "dev"}, "alice")
    assert res == {"operation_id": "a" * 32}

    # ── 7. exécute work() et vérifie l'ordre stop → start ─────────────────
    work = work_holder["work"]
    assert callable(work)
    result = await work()  # type: ignore[operator]
    assert order == ["stop", "start"]
    assert result == {"workspace": "dev", "status": "provisioning"}
