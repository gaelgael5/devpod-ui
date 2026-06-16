from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from portal.devpod.shelve import shelve_if_pending


def _make_proc(stdout: bytes, rc: int, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = rc
    return proc


@pytest.mark.asyncio
async def test_shelve_nothing_to_shelve():
    proc = _make_proc(b"NOTHING_TO_SHELVE\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {"PATH": "/usr/bin"})
    assert result is None


@pytest.mark.asyncio
async def test_shelve_returns_branch():
    proc = _make_proc(b"SHELVED:recovery-16-06-26-10-30\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {})
    assert result == "recovery-16-06-26-10-30"


@pytest.mark.asyncio
async def test_shelve_push_failure_raises_409():
    proc = _make_proc(b"", 1, stderr=b"remote: Permission denied\n")
    mock_exec = AsyncMock(return_value=proc)
    with (
        patch("asyncio.create_subprocess_exec", mock_exec),
        pytest.raises(HTTPException) as exc_info,
    ):
        await shelve_if_pending(["devpod"], "alice-myws", {})
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail  # non-vide


@pytest.mark.asyncio
async def test_shelve_unexpected_output_rc0_returns_none():
    """rc=0 mais sortie inattendue → dégradation gracieuse → None (allow delete)."""
    proc = _make_proc(b"some unexpected devpod output\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {})
    assert result is None


@pytest.mark.asyncio
async def test_shelve_passes_correct_command():
    proc = _make_proc(b"NOTHING_TO_SHELVE\n", 0)
    captured: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        captured.append(args)
        return proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        await shelve_if_pending(["devpod"], "alice-myws", {})

    cmd = captured[0]
    assert "devpod" in cmd
    assert "ssh" in cmd
    assert "alice-myws" in cmd
    assert "--command" in cmd
    assert "base64 -d" in cmd[cmd.index("--command") + 1]
