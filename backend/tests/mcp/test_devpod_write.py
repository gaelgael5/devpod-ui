# backend/tests/mcp/test_devpod_write.py
"""Impls workspace_mkdir / write_file (atomique I-6) / exec (ws_exec mocké)."""
from __future__ import annotations

import hashlib

import pytest

from portal.mcp import devpod_tools


def _capture(monkeypatch, rc=0, out=""):  # noqa: ANN001, ANN202
    calls: list[str] = []

    async def fake(login, ws_id, cmd, timeout=30.0):  # noqa: ANN001, ANN202
        calls.append(cmd)
        return (rc, out)

    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    return calls


@pytest.mark.asyncio
async def test_mkdir(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await devpod_tools._workspace_mkdir(None, {"workspace": "dev", "path": "a/b"}, "admin")
    assert res == {"path": "a/b"}
    assert "mkdir -p" in calls[0] and "/workspaces/dev/a/b" in calls[0]


@pytest.mark.asyncio
async def test_write_file_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await devpod_tools._workspace_write_file(
        None, {"workspace": "dev", "path": "x.txt", "content": "hi"}, "admin"
    )
    assert res["sha256"] == hashlib.sha256(b"hi").hexdigest()
    assert res["bytes"] == 2
    assert "mktemp" in calls[0] and "mv -f" in calls[0]  # tempfile + rename atomique
    assert "mkdir -p" in calls[0]  # create_dirs défaut true


@pytest.mark.asyncio
async def test_write_file_no_create_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await devpod_tools._workspace_write_file(
        None, {"workspace": "dev", "path": "x.txt", "content": "hi", "create_dirs": False}, "admin"
    )
    assert not calls[0].lstrip().startswith("mkdir")


@pytest.mark.asyncio
async def test_write_file_rejects_escape() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_write_file(
            None, {"workspace": "dev", "path": "../x", "content": "c"}, "admin"
        )


@pytest.mark.asyncio
async def test_exec_returns_output_and_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, rc=3, out="boom")
    res = await devpod_tools._workspace_exec(
        None, {"workspace": "dev", "command": "false"}, "admin"
    )
    assert res == {"stdout": "boom", "stderr": "", "exit_code": 3}


@pytest.mark.asyncio
async def test_exec_rejects_invalid_cwd() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_exec(
            None, {"workspace": "dev", "command": "ls", "cwd": "../x"}, "admin"
        )
