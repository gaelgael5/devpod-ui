from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_workspace_get_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(
        name="dev",
        source="git@x/y.git",
        branch="dev",
        host="node1",
        recipes=["python"],
        devcontainer_path="",
        template="",
    )
    cfg = SimpleNamespace(workspaces=[spec])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    svc_status = {"status": "running", "created_at": "2026-06-01T00:00:00Z"}
    svc = SimpleNamespace(status=AsyncMock(return_value=svc_status))
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    monkeypatch.setattr(
        devpod_tools, "_session_list", AsyncMock(return_value=[{"name": "main"}])
    )

    res = await devpod_tools._workspace_get(None, {"workspace": "dev"}, "alice")

    assert res["id"] == "alice-dev"
    assert res["name"] == "dev"
    assert res["repo"] == "git@x/y.git"
    assert res["status"] == "running"
    assert res["node"] == "node1"
    assert res["recipe"] == ["python"]
    assert res["sessions"] == [{"name": "main"}]
    assert res["created_at"] == "2026-06-01T00:00:00Z"


@pytest.mark.asyncio
async def test_workspace_get_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(workspaces=[])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_get(None, {"workspace": "ghost"}, "alice")


@pytest.mark.asyncio
async def test_workspace_logs_setup_reads_portal_log(monkeypatch, tmp_path):
    logs = tmp_path / "logs" / "alice"
    logs.mkdir(parents=True)
    (logs / "alice-dev.log").write_text("line1\nline2\nline3\n", encoding="utf-8")
    monkeypatch.setattr(devpod_tools, "_data_root", lambda: tmp_path)

    res = await devpod_tools._workspace_logs(
        None, {"workspace": "dev", "source": "setup", "lines": 2}, "alice"
    )
    assert res["source"] == "setup"
    assert res["output"].splitlines() == ["line2", "line3"]


@pytest.mark.asyncio
async def test_workspace_logs_agent_captures_pane(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        devpod_tools,
        "_session_capture",
        AsyncMock(return_value={"output": "agent-buf"}),
    )
    res = await devpod_tools._workspace_logs(
        None, {"workspace": "dev", "source": "agent"}, "alice"
    )
    assert res == {"source": "agent", "output": "agent-buf"}


@pytest.mark.asyncio
async def test_workspace_logs_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(devpod_tools, "_data_root", lambda: tmp_path)
    res = await devpod_tools._workspace_logs(
        None, {"workspace": "dev", "source": "container"}, "alice"
    )
    assert res == {"source": "container", "output": ""}
