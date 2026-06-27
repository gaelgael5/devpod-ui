# backend/tests/mcp/test_devpod_lifecycle.py
"""Impls workspace_start / stop / restart (services mockés)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SimpleNamespace(stop=AsyncMock())
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    res = await devpod_tools._workspace_stop(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "status": "stopped"}
    svc.stop.assert_awaited_once_with("admin", "admin-dev")


@pytest.mark.asyncio
async def test_start(monkeypatch: pytest.MonkeyPatch) -> None:
    start = AsyncMock(return_value="admin-dev")
    monkeypatch.setattr(devpod_tools, "_start_existing", start)
    res = await devpod_tools._workspace_start(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "status": "provisioning"}
    start.assert_awaited_once_with("admin", "dev", None)


@pytest.mark.asyncio
async def test_start_unknown_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(login, name, conn):  # noqa: ANN001, ANN202
        raise ValueError("workspace inconnu: dev")

    monkeypatch.setattr(devpod_tools, "_start_existing", boom)
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_start(None, {"workspace": "dev"}, "admin")


@pytest.mark.asyncio
async def test_restart_stops_then_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    svc = SimpleNamespace(stop=AsyncMock(side_effect=lambda *a: order.append("stop")))
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)

    async def fake_start(login, name, conn):  # noqa: ANN001, ANN202
        order.append("start")
        return "admin-dev"

    monkeypatch.setattr(devpod_tools, "_start_existing", fake_start)
    res = await devpod_tools._workspace_restart(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "status": "provisioning"}
    assert order == ["stop", "start"]
