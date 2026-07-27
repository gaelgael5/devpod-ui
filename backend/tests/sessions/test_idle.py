"""Suggestion d'arrêt des workspaces inactifs (enabler 6016436b).

Verdict de la sonde tmux (parsing panes/activité) et machine à états de la
passe : périodes d'idle, alerte unique par période, épingle, exemptions.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from portal.sessions import idle

_T0 = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


# ─── probe_workspace_idle : parsing ──────────────────────────────────────────


async def _probe_with(monkeypatch: pytest.MonkeyPatch, rc: int, output: str) -> Any:
    async def _ws_exec(login: str, ws_id: str, cmd: str) -> tuple[int, str]:
        assert "list-panes" in cmd and "session_activity" in cmd
        return rc, output

    monkeypatch.setattr(idle, "ws_exec", _ws_exec)
    return await idle.probe_workspace_idle("alice", "alice-dev")


async def test_probe_no_tmux_server_is_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    # rc=1 : aucun serveur tmux — rien d'actif, candidat (sans horodatage).
    assert await _probe_with(monkeypatch, 1, "") == ("idle", None)


async def test_probe_idle_shells_with_activity_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epoch = int(_T0.timestamp())
    out = f"{epoch - 3600} bash\n{epoch} zsh\n"
    verdict, last = await _probe_with(monkeypatch, 0, out)
    assert verdict == "idle"
    assert last == _T0  # max(session_activity)


async def test_probe_foreground_process_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epoch = int(_T0.timestamp())
    out = f"{epoch} bash\n{epoch} claude\n"
    verdict, _ = await _probe_with(monkeypatch, 0, out)
    assert verdict == "active"


async def test_probe_ssh_dead_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _probe_with(monkeypatch, 255, "") == ("unreachable", None)
    assert await _probe_with(monkeypatch, 124, "") == ("unreachable", None)


# ─── run_idle_pass : machine à états ─────────────────────────────────────────


class _Store:
    """Doublure en mémoire de db/workspace_idle + captures d'alertes."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.alerts: list[str] = []


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store = _Store()
    refs: list[dict[str, Any]] = [
        {"login": "alice", "name": "dev", "host": "", "keep_active": False},
        {"login": "alice", "name": "pinned", "host": "", "keep_active": True},
        {"login": "bob", "name": "ml", "host": "", "keep_active": False},
    ]
    statuses: dict[str, str] = {
        "alice-dev": "running",
        "alice-pinned": "running",
        "bob-ml": "running",
    }

    async def _refs(login: Any, conn: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in refs]

    async def _statuses(conn: Any) -> list[dict[str, Any]]:
        return [{"ws_id": k, "status": v} for k, v in statuses.items()]

    async def _get_all(conn: Any) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in store.rows.items()}

    async def _upsert(
        conn: Any,
        ws_id: str,
        login: str,
        idle_since: Any,
        last_activity: Any,
        now: Any,
        *,
        reset_alert: bool = False,
    ) -> None:
        row = store.rows.setdefault(ws_id, {"alerted_at": None})
        row.update(
            login=login, idle_since=idle_since, last_activity=last_activity, updated_at=now
        )
        if reset_alert:
            row["alerted_at"] = None

    async def _mark(conn: Any, ws_id: str, at: Any) -> None:
        store.rows[ws_id]["alerted_at"] = at
        store.alerts.append(ws_id)

    async def _clear(conn: Any, ws_ids: list[str]) -> None:
        for w in ws_ids:
            store.rows.pop(w, None)

    monkeypatch.setattr(idle, "list_workspace_refs", _refs)
    monkeypatch.setattr(idle, "list_all_status_db", _statuses)
    monkeypatch.setattr(idle.workspace_idle_db, "get_all", _get_all)
    monkeypatch.setattr(idle.workspace_idle_db, "upsert_idle", _upsert)
    monkeypatch.setattr(idle.workspace_idle_db, "mark_alerted", _mark)
    monkeypatch.setattr(idle.workspace_idle_db, "clear", _clear)
    return {"store": store, "refs": refs, "statuses": statuses}


def _probe(verdicts: dict[str, tuple[str, datetime | None]]) -> Any:
    async def probe_fn(login: str, ws_id: str) -> tuple[str, datetime | None]:
        return verdicts[ws_id]

    return probe_fn


async def test_pass_never_probes_pinned_workspaces(env: dict[str, Any]) -> None:
    probed: list[str] = []

    async def probe_fn(login: str, ws_id: str) -> tuple[str, datetime | None]:
        probed.append(ws_id)
        return "idle", None

    await idle.run_idle_pass(conn=object(), probe_fn=probe_fn, threshold_h=3, now=_T0)
    assert "alice-pinned" not in probed
    assert set(probed) == {"alice-dev", "bob-ml"}


async def test_idle_below_threshold_tracks_without_alert(env: dict[str, Any]) -> None:
    last = _T0 - timedelta(hours=1)
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("idle", last), "bob-ml": ("active", None)}),
        threshold_h=3,
        now=_T0,
    )
    store = env["store"]
    assert store.rows["alice-dev"]["idle_since"] == last
    assert store.alerts == []
    assert "bob-ml" not in store.rows


async def test_idle_beyond_threshold_alerts_once_per_period(env: dict[str, Any]) -> None:
    last = _T0 - timedelta(hours=5)
    verdicts = {"alice-dev": ("idle", last), "bob-ml": ("active", None)}
    await idle.run_idle_pass(conn=object(), probe_fn=_probe(verdicts), threshold_h=3, now=_T0)
    store = env["store"]
    assert store.alerts == ["alice-dev"]

    # Tick suivant, toujours idle : pas de deuxième alerte (anti-flood).
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe(verdicts),
        threshold_h=3,
        now=_T0 + timedelta(minutes=5),
    )
    assert store.alerts == ["alice-dev"]


async def test_activity_resumed_between_passes_rearms_alert(env: dict[str, Any]) -> None:
    store = env["store"]
    old = _T0 - timedelta(hours=10)
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("idle", old), "bob-ml": ("active", None)}),
        threshold_h=3,
        now=_T0,
    )
    assert store.alerts == ["alice-dev"]

    # session_activity a avancé : quelqu'un a tapé entre deux passes → nouvelle
    # période, plus de suggestion tant que le seuil n'est pas re-franchi.
    recent = _T0 - timedelta(minutes=10)
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("idle", recent), "bob-ml": ("active", None)}),
        threshold_h=3,
        now=_T0,
    )
    assert store.rows["alice-dev"]["idle_since"] == recent
    assert store.rows["alice-dev"]["alerted_at"] is None

    # Le seuil re-franchi sur la NOUVELLE période → nouvelle alerte.
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("idle", recent), "bob-ml": ("active", None)}),
        threshold_h=3,
        now=recent + timedelta(hours=4),
    )
    assert store.alerts == ["alice-dev", "alice-dev"]


async def test_unreachable_and_stopped_clear_the_period(env: dict[str, Any]) -> None:
    store = env["store"]
    last = _T0 - timedelta(hours=5)
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("idle", last), "bob-ml": ("idle", last)}),
        threshold_h=3,
        now=_T0,
    )
    assert set(store.rows) == {"alice-dev", "bob-ml"}

    # alice-dev devient injoignable (autre problème : sonde de vivacité) ;
    # bob-ml passe stopped → les deux périodes se terminent.
    env["statuses"]["bob-ml"] = "stopped"
    await idle.run_idle_pass(
        conn=object(),
        probe_fn=_probe({"alice-dev": ("unreachable", None)}),
        threshold_h=3,
        now=_T0,
    )
    assert store.rows == {}


async def test_threshold_zero_disables_the_feature(env: dict[str, Any]) -> None:
    probed: list[str] = []

    async def probe_fn(login: str, ws_id: str) -> tuple[str, datetime | None]:
        probed.append(ws_id)
        return "idle", None

    await idle.run_idle_pass(conn=object(), probe_fn=probe_fn, threshold_h=0, now=_T0)
    assert probed == []
