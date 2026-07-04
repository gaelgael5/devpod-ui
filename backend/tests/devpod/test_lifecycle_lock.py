# backend/tests/devpod/test_lifecycle_lock.py
"""Bug 003 — verrou de lifecycle par ws_id + épitaphe anti-résurrection.

Ces tests prouvent, sans Docker ni Postgres (la couche statut est mockée en mémoire),
deux invariants :

1. Exclusion mutuelle : deux opérations lifecycle sur le même ws_id ne s'entrelacent
   jamais (le subprocess devpod de la seconde ne démarre qu'après la fin de la première).
2. Anti-résurrection : un `delete` concurrent d'un `up` en cours annule l'`up` et aucune
   ligne `running` ne survit à la suppression — même chemin garanti par l'écriture finale
   gardée (_write_status_if_exists) qui ne recrée jamais une ligne supprimée.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    """Moteur factice : begin()/connect() rendent un contexte async sans DB réelle."""

    def begin(self) -> _FakeConn:
        return _FakeConn()

    def connect(self) -> _FakeConn:
        return _FakeConn()


@pytest.fixture
def status_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Remplace la couche DB statut par un dict en mémoire (conn ignoré)."""
    import portal.devpod.service as service_mod

    store: dict[str, dict[str, Any]] = {}

    async def fake_upsert(
        ws_id: str, status: str, conn: Any, login: str = "", **extra: Any
    ) -> None:
        store[ws_id] = {"ws_id": ws_id, "status": status, "login": login, **extra}

    async def fake_update_if_exists(
        ws_id: str, status: str, conn: Any, login: str = "", **extra: Any
    ) -> bool:
        if ws_id not in store:
            return False
        store[ws_id].update({"status": status, "login": login, **extra})
        return True

    async def fake_delete(ws_id: str, conn: Any) -> None:
        store.pop(ws_id, None)

    async def fake_get(ws_id: str, conn: Any) -> dict[str, Any] | None:
        return store.get(ws_id)

    async def fake_persist_log(*args: Any, **kwargs: Any) -> None:
        return None

    class _FakeMsgDb:
        @staticmethod
        async def purge_workspace_messages(*args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(service_mod, "upsert_status_db", fake_upsert)
    monkeypatch.setattr(service_mod, "update_status_if_exists_db", fake_update_if_exists)
    monkeypatch.setattr(service_mod, "delete_status_db", fake_delete)
    monkeypatch.setattr(service_mod, "get_status_db", fake_get)
    monkeypatch.setattr(service_mod, "persist_log_blob_from_file", fake_persist_log)
    monkeypatch.setattr(service_mod, "_msg_db", _FakeMsgDb())
    return store


def _make_service(global_cfg: Any, fake_devpod_bin: list[str]):
    from portal.devpod.service import DevPodService

    return DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin, exposure=None)


async def test_write_status_if_exists_never_resurrects(
    status_store: dict[str, dict[str, Any]], global_cfg: Any, fake_devpod_bin: list[str]
) -> None:
    """Épitaphe : écrire un statut sur un ws_id absent ne crée pas de ligne."""
    svc = _make_service(global_cfg, fake_devpod_bin)

    written = await svc._write_status_if_exists("alice-ghost", "running", login="alice")
    assert written is False
    assert "alice-ghost" not in status_store

    await svc._write_status("alice-app", "provisioning", login="alice")
    written2 = await svc._write_status_if_exists("alice-app", "running", login="alice")
    assert written2 is True
    assert status_store["alice-app"]["status"] == "running"


async def test_lifecycle_lock_serializes_up_tasks(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux _run_up_task sur le même ws_id ne s'entrelacent jamais."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    await svc._write_status("bob-app", "provisioning", login="bob")

    events: list[str] = []

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        events.append(f"enter:{id(cmd)}")
        await asyncio.sleep(0.05)
        events.append("exit")
        return 0

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)

    t1 = asyncio.create_task(svc._run_up_task("bob-app", "img", None, {}, "bob"))
    t2 = asyncio.create_task(svc._run_up_task("bob-app", "img", None, {}, "bob"))
    await asyncio.gather(t1, t2)

    # Aucun entrelacement : chaque enter est immédiatement suivi de son exit.
    assert events[0].startswith("enter")
    assert events[1] == "exit"
    assert events[2].startswith("enter")
    assert events[3] == "exit"
    assert status_store["bob-app"]["status"] == "running"


async def test_delete_cancels_inflight_up_no_zombie(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete pendant un up en cours : l'up est annulé, aucune ligne ne survit."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    login, ws_id = "carol", "carol-app"
    await svc._write_status(ws_id, "provisioning", login=login)

    up_in_subprocess = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        if "up" in cmd:
            up_in_subprocess.set()
            await release.wait()  # bloque jusqu'à annulation
            return 0
        return 0  # devpod delete/stop

    async def fake_kill(ws_id: str) -> None:
        # Débloque le faux subprocess up comme le ferait un vrai kill.
        release.set()

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(service_mod, "kill_if_running", fake_kill)

    task = asyncio.create_task(svc._run_up_task(ws_id, "img", None, {}, login))
    svc._up_tasks[ws_id] = task
    await asyncio.wait_for(up_in_subprocess.wait(), timeout=2.0)  # up détient le verrou

    result = await svc.delete(login, ws_id, shelve=False)

    assert result == {"deleted": True, "recovery_branch": None}
    assert ws_id not in status_store, "la ligne ne doit pas survivre au delete"
    assert task.done()
    # L'up a été interrompu avant toute écriture 'running'.
    assert task.cancelled() or task.exception() is None


async def test_stop_on_deleted_workspace_does_not_resurrect(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 007 : stop() sur un workspace déjà supprimé (ligne absente) ne doit
    recréer aucune ligne — ni « unknown » (échec devpod stop) ni « stopped »."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)

    rc_holder = {"rc": 1}

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        return rc_holder["rc"]

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)

    # devpod stop échoue (workspace inexistant) → pas de ligne « unknown »
    await svc.stop("eve", "eve-app")
    assert "eve-app" not in status_store

    # devpod stop « réussit » → pas non plus de ligne « stopped » fantôme
    rc_holder["rc"] = 0
    await svc.stop("eve", "eve-app")
    assert "eve-app" not in status_store


async def test_stop_on_existing_workspace_updates_status(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop() sur un workspace existant écrit bien « stopped » (chemin nominal)."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    await svc._write_status("eve-app", "running", login="eve")

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        return 0

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)

    await svc.stop("eve", "eve-app")
    assert status_store["eve-app"]["status"] == "stopped"


async def test_delete_after_up_completed_leaves_no_row(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """up terminé (running) puis delete : la ligne est bien supprimée, pas de fantôme."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    login, ws_id = "dan", "dan-app"
    await svc._write_status(ws_id, "provisioning", login=login)

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        return 0

    async def fake_kill(ws_id: str) -> None:
        return None

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(service_mod, "kill_if_running", fake_kill)

    task = asyncio.create_task(svc._run_up_task(ws_id, "img", None, {}, login))
    svc._up_tasks[ws_id] = task
    await task
    assert status_store[ws_id]["status"] == "running"

    await svc.delete(login, ws_id, shelve=False)
    assert ws_id not in status_store
