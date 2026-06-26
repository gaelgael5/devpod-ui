# backend/tests/mcp/test_devpod_workspace_read.py
"""Impls workspace_list / workspace_status (services internes mockés)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp import devpod_tools


def _spec(**kw):  # noqa: ANN003, ANN202
    return SimpleNamespace(name="dev", source="git@x/repo.git", host="node1", recipes=["py"], **kw)


@pytest.mark.asyncio
async def test_workspace_list_maps_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(workspaces=[_spec()])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    svc = SimpleNamespace(
        list_workspaces=AsyncMock(return_value=[{"ws_id": "admin-dev", "status": "running"}])
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)

    rows = await devpod_tools._workspace_list(None, {"status": "all"}, "admin")
    assert rows == [
        {
            "id": "admin-dev", "name": "dev", "repo": "git@x/repo.git", "status": "running",
            "node": "node1", "recipe": ["py"], "tags": [],
        }
    ]
    # Filtre sur un statut différent → vide.
    assert await devpod_tools._workspace_list(None, {"status": "stopped"}, "admin") == []


@pytest.mark.asyncio
async def test_workspace_status_maps_running(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SimpleNamespace(
        status=AsyncMock(return_value={"ws_id": "admin-dev", "status": "running"})
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    res = await devpod_tools._workspace_status(None, {"workspace": "dev"}, "admin")
    assert res == {
        "workspace": "dev", "health": "running", "container_up": True, "agent_up": None
    }


@pytest.mark.asyncio
async def test_workspace_status_rejects_invalid_name() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_status(None, {"workspace": "../evil"}, "admin")
