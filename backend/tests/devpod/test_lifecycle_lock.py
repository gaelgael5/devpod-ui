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

# NB : la fixture status_store (couche statut mockée en mémoire) vit dans
# conftest.py — partagée avec les tests de persistance de port (bug 001).

pytestmark = pytest.mark.asyncio


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


async def test_delete_during_provisioning_skips_shelve(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 041 : delete pendant un provisioning ne tente jamais le shelve —
    devpod ssh sur un conteneur à moitié provisionné échouait en 409 APRÈS
    avoir tué l'up, laissant un workspace zombie avec son port-forward."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    login, ws_id = "fred", "fred-app"
    await svc._write_status(ws_id, "provisioning", login=login)

    up_in_subprocess = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        if "up" in cmd:
            up_in_subprocess.set()
            await release.wait()
            return 0
        return 0

    async def fake_kill(ws_id: str) -> None:
        release.set()

    shelve_calls: list[str] = []

    async def fake_shelve(devpod_bin: Any, ws_id: str, env: Any) -> str | None:
        shelve_calls.append(ws_id)
        return "recovery-x"

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(service_mod, "kill_if_running", fake_kill)
    monkeypatch.setattr(service_mod, "shelve_if_pending", fake_shelve)

    task = asyncio.create_task(svc._run_up_task(ws_id, "img", None, {}, login))
    svc._up_tasks[ws_id] = task
    await asyncio.wait_for(up_in_subprocess.wait(), timeout=2.0)

    result = await svc.delete(login, ws_id, shelve=True)

    assert shelve_calls == [], "aucun shelve sur un workspace en provisioning"
    assert result == {"deleted": True, "recovery_branch": None}
    assert ws_id not in status_store


async def test_delete_running_shelves_before_teardown(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chemin nominal : workspace running → shelve tenté, branche remontée."""
    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    login, ws_id = "gina", "gina-app"
    await svc._write_status(ws_id, "running", login=login)

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        return 0

    async def fake_shelve(devpod_bin: Any, ws_id: str, env: Any) -> str | None:
        return "recovery-1"

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(service_mod, "shelve_if_pending", fake_shelve)

    result = await svc.delete(login, ws_id, shelve=True)
    assert result == {"deleted": True, "recovery_branch": "recovery-1"}
    assert ws_id not in status_store


async def test_delete_aborts_intact_when_shelve_fails(
    status_store: dict[str, dict[str, Any]],
    global_cfg: Any,
    fake_devpod_bin: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shelve en échec (409) sur un workspace running : la suppression est
    annulée AVANT tout démontage — la ligne et le statut restent intacts."""
    from fastapi import HTTPException

    import portal.devpod.service as service_mod

    svc = _make_service(global_cfg, fake_devpod_bin)
    login, ws_id = "hugo", "hugo-app"
    await svc._write_status(ws_id, "running", login=login)

    async def fake_shelve(devpod_bin: Any, ws_id: str, env: Any) -> str | None:
        raise HTTPException(status_code=409, detail="push failed")

    forward_stops: list[str] = []

    async def fake_stop_forward(ws_id: str) -> None:
        forward_stops.append(ws_id)

    monkeypatch.setattr(service_mod, "shelve_if_pending", fake_shelve)
    monkeypatch.setattr(svc, "_stop_port_forward", fake_stop_forward)

    with pytest.raises(HTTPException):
        await svc.delete(login, ws_id, shelve=True)

    assert status_store[ws_id]["status"] == "running"
    assert forward_stops == [], "le tunnel ne doit pas être démonté si le shelve échoue"


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
