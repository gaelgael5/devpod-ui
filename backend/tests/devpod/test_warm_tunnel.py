"""Pré-chauffe du tunnel SSH (ControlMaster) — tranche 2 de la refonte des sessions.

`warm_tunnel` est best-effort : elle monte le master via un `true` et ne lève
jamais. Tests par substitution de `ws_exec` (pas de vrai SSH).
"""

from __future__ import annotations

import asyncio

import pytest

import portal.devpod.exec as exec_mod
from portal.devpod.exec import warm_tunnel


@pytest.fixture(autouse=True)
def _clean_warm_state() -> None:
    """L'état de pré-chauffage est global au module : repartir à blanc."""
    exec_mod.reset_warm_state()
    yield
    exec_mod.reset_warm_state()


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


class TestWarmTunnelDeduplication:
    """Anti-empilement (incident 30/08).

    `_warm_running_tunnels` rappelle `warm_tunnel` à chaque rafraîchissement de
    l'agrégat (~8 s). Tant que le tunnel est froid, chaque appel montait un
    handshake `devpod ssh --stdio` de plus, tué au bout de 20 s — sur un nœud
    déjà saturé ça n'ajoutait que de la charge. Un seul pré-chauffage en vol par
    ws_id, et pas de nouvelle tentative avant l'expiration du délai posé.
    """

    @pytest.mark.asyncio
    async def test_no_second_handshake_while_one_is_inflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        calls: list[str] = []

        async def fake(
            login: str, ws_id: str, command: str, timeout: float = 30.0
        ) -> tuple[int, str]:
            calls.append(ws_id)
            await release.wait()
            return 0, ""

        monkeypatch.setattr(exec_mod, "ws_exec", fake)

        inflight = asyncio.create_task(warm_tunnel("alice", "alice-proj"))
        await asyncio.sleep(0)  # laisse la tâche atteindre son premier await

        assert await warm_tunnel("alice", "alice-proj") is False  # aucun verdict encore

        release.set()
        assert await inflight is True
        assert calls == ["alice-proj"]

    @pytest.mark.asyncio
    async def test_failure_opens_a_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        async def fake(*a: object, **k: object) -> tuple[int, str]:
            calls.append("x")
            return exec_mod.TIMEOUT_RC, "SSH command timed out"

        monkeypatch.setattr(exec_mod, "ws_exec", fake)

        assert await warm_tunnel("alice", "alice-proj") is False
        assert await warm_tunnel("alice", "alice-proj") is False
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_success_is_not_re_warmed_within_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake(*a: object, **k: object) -> tuple[int, str]:
            calls.append("x")
            return 0, ""

        monkeypatch.setattr(exec_mod, "ws_exec", fake)

        assert await warm_tunnel("alice", "alice-proj") is True
        assert await warm_tunnel("alice", "alice-proj") is True
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_cooldown_expiry_allows_a_new_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake(*a: object, **k: object) -> tuple[int, str]:
            calls.append("x")
            return exec_mod.TIMEOUT_RC, "SSH command timed out"

        monkeypatch.setattr(exec_mod, "ws_exec", fake)
        monkeypatch.setattr(exec_mod, "_WARM_FAILURE_COOLDOWN_S", 0.0)

        await warm_tunnel("alice", "alice-proj")
        await warm_tunnel("alice", "alice-proj")
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_workspaces_do_not_share_their_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake(
            login: str, ws_id: str, command: str, timeout: float = 30.0
        ) -> tuple[int, str]:
            calls.append(ws_id)
            return 0, ""

        monkeypatch.setattr(exec_mod, "ws_exec", fake)

        await warm_tunnel("alice", "alice-proj")
        await warm_tunnel("alice", "alice-other")
        assert calls == ["alice-proj", "alice-other"]

    @pytest.mark.asyncio
    async def test_reset_forgets_the_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Une mutation de cycle de vie doit pouvoir re-chauffer immédiatement."""
        calls: list[str] = []

        async def fake(*a: object, **k: object) -> tuple[int, str]:
            calls.append("x")
            return 0, ""

        monkeypatch.setattr(exec_mod, "ws_exec", fake)

        await warm_tunnel("alice", "alice-proj")
        exec_mod.reset_warm_state()
        await warm_tunnel("alice", "alice-proj")
        assert len(calls) == 2
