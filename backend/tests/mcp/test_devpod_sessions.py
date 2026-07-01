# backend/tests/mcp/test_devpod_sessions.py
"""Impls session_open/send/capture/list/get (ws_exec mocké)."""
from __future__ import annotations

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
async def test_open_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await devpod_tools._session_open(
        None, {"workspace": "dev", "command": "claude"}, "admin"
    )
    assert res == {
        "session_id": "dev:main", "workspace": "dev", "name": "main", "command": "claude"
    }
    assert "has-session" in calls[0] and "new-session" in calls[0]


@pytest.mark.asyncio
async def test_send_submits_with_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await devpod_tools._session_send(None, {"workspace": "dev", "text": "hi"}, "admin")
    assert res == {"sent": True}
    assert "send-keys" in calls[0] and "Enter" in calls[0]


@pytest.mark.asyncio
async def test_send_without_submit_omits_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await devpod_tools._session_send(
        None, {"workspace": "dev", "text": "hi", "submit": False}, "admin"
    )
    assert "Enter" not in calls[0]


@pytest.mark.asyncio
async def test_capture_keeps_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch, out="screen")
    res = await devpod_tools._session_capture(None, {"workspace": "dev"}, "admin")
    assert res == {"output": "screen"}
    assert "capture-pane" in calls[0] and "-e" in calls[0]


@pytest.mark.asyncio
async def test_list_parses_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, out="main|node\nbuild|python")
    res = await devpod_tools._session_list(None, {"workspace": "dev"}, "admin")
    assert res == [
        {"session_id": "dev:main", "name": "main", "command": "node", "alive": True,
         "uptime_s": None},
        {"session_id": "dev:build", "name": "build", "command": "python", "alive": True,
         "uptime_s": None},
    ]


@pytest.mark.asyncio
async def test_get_parses_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, out="main|%0|claude|0")
    res = await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
    assert res["session_id"] == "dev:main"
    assert res["pane_id"] == "%0" and res["command"] == "claude" and res["alive"] is True
    assert res["uptime_s"] >= 0


@pytest.mark.asyncio
async def test_get_missing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, out="")
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
