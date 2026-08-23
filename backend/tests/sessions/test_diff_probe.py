"""Émetteur de diff sur la sonde tmux (sessions hors-portail).

Tout est monkeypatché (sonde, emit, DB) : ces tests tournent sans Postgres/Docker.
Couvre : diff pur, seed silencieux, détection created/closed hors-portail, absence
de double émission avec les mutations du portail, injoignabilité, purge.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.sessions import diff_probe as dp


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    dp.reset_state()
    yield
    dp.reset_state()


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _emit(event_type: str, **kwargs: Any) -> None:
        calls.append({"type": event_type, **kwargs})

    monkeypatch.setattr("portal.events.bus.emit_event", _emit)
    return calls


def _patch_probe(monkeypatch: pytest.MonkeyPatch, result: tuple[int, list[str]]) -> None:
    async def _probe(login: str, ws_id: str) -> tuple[int, list[str]]:
        return result

    monkeypatch.setattr(dp, "probe_workspace_sessions", _probe)


def test_compute_session_diff() -> None:
    appeared, disappeared = dp.compute_session_diff({"a", "b"}, {"b", "c"})
    assert appeared == ["c"]
    assert disappeared == ["a"]


@pytest.mark.asyncio
async def test_seed_is_silent(monkeypatch: pytest.MonkeyPatch, emitted: list[dict]) -> None:
    _patch_probe(monkeypatch, (0, ["work", "logs"]))
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (0, 0)
    assert emitted == []
    assert dp._known["alice-proj"] == {"work", "logs"}


@pytest.mark.asyncio
async def test_detects_out_of_portal_created(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    _patch_probe(monkeypatch, (0, ["work"]))
    await dp._reconcile_workspace("alice", "alice-proj")  # seed
    _patch_probe(monkeypatch, (0, ["work", "rogue"]))
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (1, 0)
    assert len(emitted) == 1
    assert emitted[0]["type"] == "session.created"
    assert emitted[0]["actor"] == "system"
    assert emitted[0]["workspace"] == "proj"
    assert emitted[0]["subject"]["session"] == "rogue"


@pytest.mark.asyncio
async def test_detects_out_of_portal_closed(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    _patch_probe(monkeypatch, (0, ["work", "doomed"]))
    await dp._reconcile_workspace("alice", "alice-proj")  # seed
    _patch_probe(monkeypatch, (0, ["work"]))
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (0, 1)
    assert emitted[0]["type"] == "session.closed"
    assert emitted[0]["subject"]["session"] == "doomed"


@pytest.mark.asyncio
async def test_portal_created_not_reemitted(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    _patch_probe(monkeypatch, (0, ["work"]))
    await dp._reconcile_workspace("alice", "alice-proj")  # seed
    # Le portail crée « feature » : marqué connu → la sonde ne doit pas le ré-émettre.
    dp.note_session_created("alice-proj", "feature")
    _patch_probe(monkeypatch, (0, ["work", "feature"]))
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (0, 0)
    assert emitted == []


@pytest.mark.asyncio
async def test_portal_closed_not_reemitted(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    _patch_probe(monkeypatch, (0, ["work", "temp"]))
    await dp._reconcile_workspace("alice", "alice-proj")  # seed
    dp.note_session_closed("alice-proj", "temp")  # le portail ferme temp
    _patch_probe(monkeypatch, (0, ["work"]))
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (0, 0)
    assert emitted == []


@pytest.mark.asyncio
async def test_unreachable_emits_nothing(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    _patch_probe(monkeypatch, (0, ["work"]))
    await dp._reconcile_workspace("alice", "alice-proj")  # seed
    _patch_probe(monkeypatch, (1, []))  # injoignable : rc != 0
    created, closed = await dp._reconcile_workspace("alice", "alice-proj")
    assert (created, closed) == (0, 0)
    assert emitted == []
    # L'état connu n'est pas écrasé par une sonde ratée.
    assert dp._known["alice-proj"] == {"work"}


@pytest.mark.asyncio
async def test_probe_once_purges_gone_workspaces(
    monkeypatch: pytest.MonkeyPatch, emitted: list[dict]
) -> None:
    class _Acm:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *a: object) -> bool:
            return False

    class _Engine:
        def connect(self) -> _Acm:
            return _Acm()

    monkeypatch.setattr("portal.db.engine._get_engine", lambda: _Engine())

    running = [{"login": "alice", "ws_id": "alice-proj"}]

    async def _list_running(conn: object) -> list[dict[str, str]]:
        return running

    monkeypatch.setattr("portal.db.workspace_status.list_running_db", _list_running)
    _patch_probe(monkeypatch, (0, ["work"]))

    await dp.probe_once()  # seed alice-proj
    assert "alice-proj" in dp._seeded
    # Le workspace n'est plus running : la passe suivante purge son état.
    running.clear()
    await dp.probe_once()
    assert "alice-proj" not in dp._seeded
    assert "alice-proj" not in dp._known
