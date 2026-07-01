# backend/tests/mcp/test_devpod_workspace_read.py
"""Impls workspace_list / workspace_status (services internes mockés)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
async def test_workspace_status_running_agent_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container running + ws_exec rc=0 → agent_up=True."""
    svc = SimpleNamespace(
        status=AsyncMock(return_value={"ws_id": "admin-dev", "status": "running"})
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    with patch("portal.mcp.devpod_tools.ws_exec", AsyncMock(return_value=(0, ""))):
        res = await devpod_tools._workspace_status(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "health": "running", "container_up": True, "agent_up": True}


@pytest.mark.asyncio
async def test_workspace_status_running_agent_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container running mais ws_exec rc≠0 (SSH timeout) → agent_up=False."""
    svc = SimpleNamespace(
        status=AsyncMock(return_value={"ws_id": "admin-dev", "status": "running"})
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    with patch("portal.mcp.devpod_tools.ws_exec", AsyncMock(return_value=(1, "SSH command timed out"))):
        res = await devpod_tools._workspace_status(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "health": "running", "container_up": True, "agent_up": False}


@pytest.mark.asyncio
async def test_workspace_status_container_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container stopped → agent_up=None (pas de probe), ws_exec non appelé."""
    svc = SimpleNamespace(
        status=AsyncMock(return_value={"ws_id": "admin-dev", "status": "stopped"})
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    with patch("portal.mcp.devpod_tools.ws_exec", AsyncMock()) as mock_exec:
        res = await devpod_tools._workspace_status(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "health": "stopped", "container_up": False, "agent_up": None}
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_status_rejects_invalid_name() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_status(None, {"workspace": "../evil"}, "admin")
