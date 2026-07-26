"""Sonde de vivacité des hosts (enabler 727ee81d).

Logique d'hystérésis, extraction de la cible TCP, et orchestration d'une passe
(les I/O — check TCP et écritures DB — sont substituées).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from portal.nodes import liveness

# ─── evaluate : hystérésis ────────────────────────────────────────────────────


def test_first_success_from_unknown_is_a_transition() -> None:
    assert liveness.evaluate(None, 0, ok=True, threshold=3) == (True, 0)


def test_success_when_already_reachable_is_no_transition() -> None:
    assert liveness.evaluate(True, 0, ok=True, threshold=3) == (None, 0)


def test_single_failure_does_not_transition() -> None:
    # Hoquet réseau d'un tick : pas d'alerte.
    assert liveness.evaluate(True, 0, ok=False, threshold=3) == (None, 1)
    assert liveness.evaluate(True, 1, ok=False, threshold=3) == (None, 2)


def test_threshold_consecutive_failures_transition_to_unreachable() -> None:
    assert liveness.evaluate(True, 2, ok=False, threshold=3) == (False, 3)


def test_failures_when_already_unreachable_stay_silent() -> None:
    # L'alerte est émise sur transition, pas à chaque tick.
    assert liveness.evaluate(False, 3, ok=False, threshold=3) == (None, 4)


def test_recovery_is_immediate_and_resets_failures() -> None:
    assert liveness.evaluate(False, 7, ok=True, threshold=3) == (True, 0)


def test_success_resets_failure_streak() -> None:
    # 2 échecs puis 1 réussite puis 2 échecs : jamais 3 consécutifs → pas de bascule.
    state, failures = liveness.evaluate(True, 0, ok=False, threshold=3)
    assert (state, failures) == (None, 1)
    state, failures = liveness.evaluate(True, failures, ok=False, threshold=3)
    assert (state, failures) == (None, 2)
    state, failures = liveness.evaluate(True, failures, ok=True, threshold=3)
    assert (state, failures) == (None, 0)
    state, failures = liveness.evaluate(True, failures, ok=False, threshold=3)
    assert (state, failures) == (None, 1)


# ─── probe_target ─────────────────────────────────────────────────────────────


def _host(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "name": "h",
        "type": "docker-tls",
        "docker_host": "",
        "address": "",
        "usage": "workspaces",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_probe_target_docker_tls_uses_daemon_port() -> None:
    h = _host(docker_host="tcp://192.168.10.175:2376")
    assert liveness.probe_target(h) == ("192.168.10.175", 2376)


def test_probe_target_docker_tls_defaults_to_2376() -> None:
    h = _host(docker_host="tcp://node1.lan")
    assert liveness.probe_target(h) == ("node1.lan", 2376)


def test_probe_target_ssh_uses_port_22() -> None:
    h = _host(type="ssh", address="debian@192.168.10.179")
    assert liveness.probe_target(h) == ("192.168.10.179", 22)


def test_probe_target_without_address_is_none() -> None:
    assert liveness.probe_target(_host()) is None
    assert liveness.probe_target(_host(type="ssh", address="")) is None


# ─── run_liveness_pass : orchestration ────────────────────────────────────────


@pytest.fixture
def probe_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Passe câblée sur des stubs : config 2 hosts (+1 test), DB en mémoire."""
    cfg = SimpleNamespace(
        hosts=[
            _host(name="node1", docker_host="tcp://10.0.0.1:2376"),
            _host(name="node2", type="ssh", address="debian@10.0.0.2"),
            _host(name="vm-test", type="ssh", address="debian@10.0.0.9", usage="tests"),
        ]
    )
    monkeypatch.setattr(liveness, "get_optional_cached_global", lambda: cfg)

    store: dict[str, dict[str, Any]] = {}

    async def _get_all(conn: Any) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in store.items()}

    async def _record_success(
        conn: Any, name: str, now: Any, *, transitioned: bool
    ) -> None:
        row = store.setdefault(name, {"reachable": None, "last_seen": None, "changed_at": None})
        row["reachable"] = True
        row["last_seen"] = now
        if transitioned:
            row["changed_at"] = now

    async def _record_unreachable(conn: Any, name: str, now: Any) -> None:
        row = store.setdefault(name, {"reachable": None, "last_seen": None, "changed_at": None})
        row["reachable"] = False
        row["changed_at"] = now

    async def _prune_absent(conn: Any, names: set[str]) -> None:
        for k in list(store):
            if k not in names:
                del store[k]

    monkeypatch.setattr(liveness.host_health_db, "get_all", _get_all)
    monkeypatch.setattr(liveness.host_health_db, "record_success", _record_success)
    monkeypatch.setattr(liveness.host_health_db, "record_unreachable", _record_unreachable)
    monkeypatch.setattr(liveness.host_health_db, "prune_absent", _prune_absent)
    liveness.reset_state()
    return {"cfg": cfg, "store": store}


def _check(results: dict[str, bool]) -> Any:
    async def check_fn(hostname: str, port: int) -> bool:
        return results[hostname]

    return check_fn


async def test_pass_probes_and_persists(probe_env: dict[str, Any]) -> None:
    await liveness.run_liveness_pass(
        conn=object(), check_fn=_check({"10.0.0.1": True, "10.0.0.2": True}), threshold=3
    )
    store = probe_env["store"]
    assert store["node1"]["reachable"] is True
    assert store["node1"]["last_seen"] is not None
    assert store["node2"]["reachable"] is True
    # Les VM de test (éphémères) ne sont pas sondées.
    assert "vm-test" not in store


async def test_pass_applies_hysteresis_before_marking_down(
    probe_env: dict[str, Any],
) -> None:
    up = _check({"10.0.0.1": True, "10.0.0.2": True})
    down = _check({"10.0.0.1": False, "10.0.0.2": True})
    await liveness.run_liveness_pass(conn=object(), check_fn=up, threshold=3)
    store = probe_env["store"]

    await liveness.run_liveness_pass(conn=object(), check_fn=down, threshold=3)
    assert store["node1"]["reachable"] is True  # 1 échec : pas encore
    await liveness.run_liveness_pass(conn=object(), check_fn=down, threshold=3)
    assert store["node1"]["reachable"] is True  # 2 échecs : toujours pas
    await liveness.run_liveness_pass(conn=object(), check_fn=down, threshold=3)
    assert store["node1"]["reachable"] is False  # 3 échecs consécutifs : bascule
    assert store["node2"]["reachable"] is True  # l'autre host n'est pas affecté


async def test_pass_recovers_at_first_success(probe_env: dict[str, Any]) -> None:
    down = _check({"10.0.0.1": False, "10.0.0.2": True})
    up = _check({"10.0.0.1": True, "10.0.0.2": True})
    for _ in range(3):
        await liveness.run_liveness_pass(conn=object(), check_fn=down, threshold=3)
    store = probe_env["store"]
    assert store["node1"]["reachable"] is False

    await liveness.run_liveness_pass(conn=object(), check_fn=up, threshold=3)
    assert store["node1"]["reachable"] is True


async def test_pass_prunes_removed_hosts(probe_env: dict[str, Any]) -> None:
    await liveness.run_liveness_pass(
        conn=object(), check_fn=_check({"10.0.0.1": True, "10.0.0.2": True}), threshold=3
    )
    probe_env["cfg"].hosts = [probe_env["cfg"].hosts[0]]  # node2 retiré de la config
    await liveness.run_liveness_pass(
        conn=object(), check_fn=_check({"10.0.0.1": True}), threshold=3
    )
    assert "node2" not in probe_env["store"]
