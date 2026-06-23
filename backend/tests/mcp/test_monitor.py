from __future__ import annotations

from portal.mcp.monitor import (
    BackendHealth,
    get_health,
    health_snapshot,
    reset_health,
    set_health,
)


def test_get_health_unknown_by_default() -> None:
    reset_health()
    assert get_health("b1") == BackendHealth(status="unknown")


def test_set_and_get_health() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    set_health("b2", BackendHealth(status="down", error="boom"))
    assert get_health("b1").status == "up"
    assert get_health("b2") == BackendHealth(status="down", error="boom")


def test_health_snapshot_is_copy() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    snap = health_snapshot()
    set_health("b2", BackendHealth(status="up"))
    assert "b2" not in snap  # snapshot pris avant n'est pas muté
    assert snap["b1"].status == "up"
