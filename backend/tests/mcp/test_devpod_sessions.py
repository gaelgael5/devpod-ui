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
    res = await devpod_tools._session_open(None, {"workspace": "dev", "command": "claude"}, "admin")
    assert res == {
        "session_id": "dev:main",
        "workspace": "dev",
        "name": "main",
        "command": "claude",
    }
    assert "has-session" in calls[0] and "new-session" in calls[0]


@pytest.mark.asyncio
async def test_send_submits_with_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await devpod_tools._session_send(None, {"workspace": "dev", "text": "hi"}, "admin")
    assert res == {"sent": True}
    # Correctif spec 32 §3 : un seul appel ws_exec avec -l (littéral) ET Enter (séparé).
    assert len(calls) == 1
    assert "-l" in calls[0] and "Enter" in calls[0]


@pytest.mark.asyncio
async def test_send_without_submit_omits_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await devpod_tools._session_send(
        None, {"workspace": "dev", "text": "hi", "submit": False}, "admin"
    )
    assert len(calls) == 1
    assert "Enter" not in calls[0]
    assert "-l" in calls[0]


@pytest.mark.asyncio
async def test_send_text_with_submit_contains_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await devpod_tools._session_send(None, {"workspace": "dev", "text": "do it"}, "admin")
    # Le délai anti-bracketed-paste doit être dans la commande shell composée.
    assert "sleep" in calls[0]


@pytest.mark.asyncio
async def test_send_empty_text_with_submit_sends_enter_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture(monkeypatch)
    await devpod_tools._session_send(
        None, {"workspace": "dev", "text": "", "submit": True}, "admin"
    )
    assert len(calls) == 1
    assert "Enter" in calls[0]
    # Pas de -l quand le texte est vide (Enter seul).
    assert "-l" not in calls[0]


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
        {
            "session_id": "dev:main",
            "name": "main",
            "command": "node",
            "alive": True,
            "uptime_s": None,
        },
        {
            "session_id": "dev:build",
            "name": "build",
            "command": "python",
            "alive": True,
            "uptime_s": None,
        },
    ]


_HASH_A = "a" * 64
_HASH_B = "b" * 64


@pytest.mark.asyncio
async def test_get_parses_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sortie composée : méta + hash1 + hash2 (spec 32 §4).
    _capture(monkeypatch, out=f"main|%0|claude|0\n{_HASH_A}\n{_HASH_A}")
    res = await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
    assert res["session_id"] == "dev:main"
    assert res["pane_id"] == "%0"
    assert res["command"] == "claude"
    assert res["foreground"] == "claude"
    assert res["alive"] is True
    assert res["uptime_s"] >= 0


@pytest.mark.asyncio
async def test_get_processing_false_when_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deux captures identiques → pane stable → processing=False.
    _capture(monkeypatch, out=f"main|%0|bash|0\n{_HASH_A}\n{_HASH_A}")
    res = await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
    assert res["processing"] is False


@pytest.mark.asyncio
async def test_get_processing_true_when_changing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deux captures différentes → pane change → processing=True.
    _capture(monkeypatch, out=f"main|%0|claude|0\n{_HASH_A}\n{_HASH_B}")
    res = await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
    assert res["processing"] is True


@pytest.mark.asyncio
async def test_get_foreground_reflects_pane_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, out=f"main|%0|codex|0\n{_HASH_A}\n{_HASH_A}")
    res = await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
    assert res["foreground"] == "codex"


@pytest.mark.asyncio
async def test_get_missing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, out="")
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._session_get(None, {"workspace": "dev"}, "admin")
