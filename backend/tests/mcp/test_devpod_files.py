# backend/tests/mcp/test_devpod_files.py
"""Impls workspace_read_file / workspace_tree (ws_exec mocké)."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_read_file_returns_content_and_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, "hello")))
    res = await devpod_tools._workspace_read_file(
        None, {"workspace": "dev", "path": "a.txt"}, "admin"
    )
    assert res["content"] == "hello"
    assert res["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert res["size"] == 5
    assert res["path"] == "a.txt"


@pytest.mark.asyncio
async def test_read_file_rejects_escape() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_read_file(
            None, {"workspace": "dev", "path": "../etc/passwd"}, "admin"
        )


@pytest.mark.asyncio
async def test_read_file_error_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(1, "No such file")))
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_read_file(
            None, {"workspace": "dev", "path": "a.txt"}, "admin"
        )


@pytest.mark.asyncio
async def test_tree_builds_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    out = "d\t.\nd\t./src\nf\t./src/a.py\nf\t./README.md"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, out)))
    tree = await devpod_tools._workspace_tree(None, {"workspace": "dev"}, "admin")
    assert tree["name"] == "." and tree["type"] == "dir"
    by_name = {c["name"]: c for c in tree["children"]}
    assert by_name["src"]["type"] == "dir"
    assert any(c["name"] == "a.py" and c["type"] == "file" for c in by_name["src"]["children"])
    assert any(c["name"] == "README.md" and c["type"] == "file" for c in tree["children"])


@pytest.mark.asyncio
async def test_tree_rejects_escape() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_tree(None, {"workspace": "dev", "path": "../x"}, "admin")
