from pathlib import Path
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
async def test_workspace_logs_setup_reads_portal_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
async def test_workspace_logs_agent_captures_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_capture = AsyncMock(return_value={"output": "agent-buf"})
    monkeypatch.setattr(
        devpod_tools,
        "_session_capture",
        mock_capture,
    )
    res = await devpod_tools._workspace_logs(
        None, {"workspace": "dev", "source": "agent"}, "alice"
    )
    assert res == {"source": "agent", "output": "agent-buf"}
    mock_capture.assert_called_once_with(
        None, {"workspace": "dev", "lines": 200}, "alice"
    )


@pytest.mark.asyncio
async def test_workspace_logs_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(devpod_tools, "_data_root", lambda: tmp_path)
    res = await devpod_tools._workspace_logs(
        None, {"workspace": "dev", "source": "container"}, "alice"
    )
    assert res == {"source": "container", "output": ""}


@pytest.mark.asyncio
async def test_workspace_resources_parses_cgroup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sortie scriptée : usage1, usage2 (cpu), mem_used, mem_max, df disk_used disk_total
    payload = "1000000\n1050000\n536870912\n1073741824\n2147483648 5368709120\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, payload)))
    res = await devpod_tools._workspace_resources(None, {"workspace": "dev"}, "alice")
    assert res["mem_used"] == 536870912
    assert res["mem_limit"] == 1073741824
    assert res["disk_used"] == 2147483648
    assert res["disk_limit"] == 5368709120
    assert isinstance(res["cpu_pct"], float)


@pytest.mark.asyncio
async def test_workspace_resources_unlimited_mem(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = "1000000\n1000000\n100\nmax\n10 100\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, payload)))
    res = await devpod_tools._workspace_resources(None, {"workspace": "dev"}, "alice")
    assert res["mem_limit"] is None


@pytest.mark.asyncio
async def test_workspace_resources_unreadable_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unreadable CPU reads: empty lines for both u1 and u2
    payload = "\n\n536870912\n1073741824\n10 100\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, payload)))
    res = await devpod_tools._workspace_resources(None, {"workspace": "dev"}, "alice")
    assert res["cpu_pct"] is None
    assert res["mem_used"] == 536870912
    assert res["mem_limit"] == 1073741824


@pytest.mark.asyncio
async def test_session_interrupt_sends_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value=(0, ""))
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    args = {"workspace": "dev", "session": "main"}
    res = await devpod_tools._session_interrupt(None, args, "alice")
    assert res == {"interrupted": True}
    sent_cmd = fake.await_args.args[2]
    assert "send-keys" in sent_cmd and "C-c" in sent_cmd


@pytest.mark.asyncio
async def test_session_close_kills_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value=(0, ""))
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._session_close(None, {"workspace": "dev", "session": "build"}, "alice")
    assert res == {"closed": True}
    assert "kill-session" in fake.await_args.args[2]


@pytest.mark.asyncio
async def test_session_close_requires_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._session_close(None, {"workspace": "dev"}, "alice")


@pytest.mark.asyncio
async def test_git_status_parses_porcelain(monkeypatch: pytest.MonkeyPatch) -> None:
    out = "## dev...origin/dev\nM  staged.py\n M unstaged.py\n?? new.py\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, out)))
    res = await devpod_tools._workspace_git_status(None, {"workspace": "dev"}, "alice")
    assert res["branch"] == "dev"
    assert res["staged"] == ["staged.py"]
    assert res["unstaged"] == ["unstaged.py"]
    assert res["untracked"] == ["new.py"]
    assert "diff" not in res


@pytest.mark.asyncio
async def test_git_status_with_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    async def fake(login, ws, cmd, timeout=30.0):
        calls.append(cmd)
        return (0, "## dev\n") if "status" in cmd else (0, "diff-body")
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._workspace_git_status(
        None, {"workspace": "dev", "with_diff": True}, "alice"
    )
    assert res["diff"] == "diff-body"


@pytest.mark.asyncio
async def test_git_status_with_diff_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(login, ws, cmd, timeout=30.0):
        if "status" in cmd:
            return (0, "## dev\n")
        else:
            return (1, "fatal: not a git repository")
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_git_status(
            None, {"workspace": "dev", "with_diff": True}, "alice"
        )


@pytest.mark.asyncio
async def test_git_commit_refuses_non_dev_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(login, ws, cmd, timeout=30.0):
        return (0, "main\n")  # rev-parse --abbrev-ref HEAD
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    with pytest.raises(devpod_tools.DevpodToolError, match="dev"):
        args = {"workspace": "dev", "message": "feat: x"}
        await devpod_tools._workspace_git_commit(None, args, "alice")


@pytest.mark.asyncio
async def test_git_commit_on_dev_with_push(monkeypatch: pytest.MonkeyPatch) -> None:
    seq = {"n": 0}
    async def fake(login, ws, cmd, timeout=30.0):
        seq["n"] += 1
        if "abbrev-ref" in cmd:
            return (0, "dev\n")
        if "rev-parse HEAD" in cmd:
            return (0, "abc123\n")
        return (0, "")
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._workspace_git_commit(
        None, {"workspace": "dev", "message": "feat: x", "push": True}, "alice"
    )
    assert res == {"commit_sha": "abc123", "branch": "dev", "pushed": True}
    assert seq["n"] == 4


@pytest.mark.asyncio
async def test_node_list_maps_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    h1 = SimpleNamespace(
        name="node1", address="10.0.0.1", docker_host="", usage="workspaces"
    )
    h2 = SimpleNamespace(
        name="ci", address="", docker_host="tcp://x:2376", usage="tests"
    )
    monkeypatch.setattr(
        devpod_tools, "load_global", lambda: SimpleNamespace(hosts=[h1, h2])
    )
    res = await devpod_tools._node_list(None, {}, "alice")
    assert res == [
        {
            "node_id": "node1",
            "name": "node1",
            "host": "10.0.0.1",
            "status": "configured",
            "capacity": None,
        }
    ]
