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
