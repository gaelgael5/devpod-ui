"""Pré-chauffe du tunnel SSH (ControlMaster) — tranche 2 de la refonte des sessions.

`warm_tunnel` est best-effort : elle monte le master via un `true` et ne lève
jamais. Tests par substitution de `ws_exec` (pas de vrai SSH).
"""

from __future__ import annotations

import pytest

import portal.devpod.exec as exec_mod
from portal.devpod.exec import warm_tunnel


class TestWarmTunnel:
    @pytest.mark.asyncio
    async def test_true_when_exec_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(
            login: str, ws_id: str, command: str, timeout: float = 30.0
        ) -> tuple[int, str]:
            assert command == "true"
            return 0, ""

        monkeypatch.setattr(exec_mod, "ws_exec", fake)
        assert await warm_tunnel("alice", "alice-proj") is True

    @pytest.mark.asyncio
    async def test_false_on_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(*a: object, **k: object) -> tuple[int, str]:
            return 255, "connection refused"

        monkeypatch.setattr(exec_mod, "ws_exec", fake)
        assert await warm_tunnel("alice", "alice-proj") is False

    @pytest.mark.asyncio
    async def test_swallows_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(*a: object, **k: object) -> tuple[int, str]:
            raise RuntimeError("boom")

        monkeypatch.setattr(exec_mod, "ws_exec", fake)
        assert await warm_tunnel("alice", "alice-proj") is False
