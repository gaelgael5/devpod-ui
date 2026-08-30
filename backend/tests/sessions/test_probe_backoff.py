"""Back-off de la sonde tmux après une injoignabilité (incident 30/08).

Une sonde qui part en timeout coûte 30 s de `ssh` + `devpod ssh --stdio` sur un
nœud déjà à genoux. La cacher 4 s comme un succès revenait à relancer ce coût en
boucle tant que le nœud ne répondait pas. Un verdict d'injoignabilité (timeout,
transport SSH) tient donc plus longtemps qu'un verdict normal.

Distinction à préserver : rc 1/127 (« joignable, aucun serveur tmux ») n'est PAS
une injoignabilité — c'est un état nominal, il garde le TTL court.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.devpod import exec as dexec
from portal.sessions import aggregate


@pytest.fixture(autouse=True)
def _clean() -> None:
    aggregate.clear_sessions_cache()
    yield
    aggregate.clear_sessions_cache()


@pytest.fixture
def probe_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Substitue ws_exec par un stub dont le rc est piloté par `rc_holder`."""
    calls: list[int] = []
    return calls


def _stub_ws_exec(rc: int, calls: list[int]) -> Any:
    async def _fake(login: str, ws_id: str, command: str, timeout: float = 30.0):
        calls.append(rc)
        return rc, "" if rc else "main\n"

    return _fake


class TestProbeBackoff:
    @pytest.mark.asyncio
    async def test_timeout_verdict_survives_the_short_ttl(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(dexec.TIMEOUT_RC, probe_calls))
        monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)  # TTL nominal expiré

        rc, sessions = await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert (rc, sessions) == (dexec.TIMEOUT_RC, [])

        for _ in range(3):
            assert await aggregate.probe_workspace_sessions("alice", "alice-ws") == (
                dexec.TIMEOUT_RC,
                [],
            )
        assert len(probe_calls) == 1

    @pytest.mark.asyncio
    async def test_ssh_transport_failure_also_backs_off(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(255, probe_calls))
        monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)

        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert len(probe_calls) == 1

    @pytest.mark.asyncio
    async def test_no_tmux_server_keeps_the_short_ttl(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        """rc=1 = joignable sans serveur tmux : surtout pas de back-off."""
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(1, probe_calls))
        monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)

        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert len(probe_calls) == 2

    @pytest.mark.asyncio
    async def test_success_keeps_the_short_ttl(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(0, probe_calls))
        monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)

        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert len(probe_calls) == 2

    @pytest.mark.asyncio
    async def test_backoff_expiry_allows_a_new_probe(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(dexec.TIMEOUT_RC, probe_calls))
        monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)
        monkeypatch.setattr(aggregate, "_WS_PROBE_FAILURE_TTL_S", 0.0)

        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert len(probe_calls) == 2

    @pytest.mark.asyncio
    async def test_mutation_clears_the_backoff(
        self, monkeypatch: pytest.MonkeyPatch, probe_calls: list[int]
    ) -> None:
        """Après une action utilisateur, on re-sonde tout de suite."""
        monkeypatch.setattr(aggregate, "ws_exec", _stub_ws_exec(dexec.TIMEOUT_RC, probe_calls))

        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        aggregate.invalidate_sessions_cache()
        await aggregate.probe_workspace_sessions("alice", "alice-ws")
        assert len(probe_calls) == 2
