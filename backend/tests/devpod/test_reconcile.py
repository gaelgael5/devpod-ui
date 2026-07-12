"""Bug 036 : reconcile_port_forwards doit référencer la task de reconnexion
fire-and-forget dans self._background_tasks — sinon rien n'empêche le GC de la
collecter en cours d'exécution (comportement documenté d'asyncio.create_task)."""
from __future__ import annotations

import asyncio

import portal.devpod.service as service_mod


class _FakeConnCM:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeEngine:
    def connect(self) -> _FakeConnCM:
        return _FakeConnCM()


async def test_reconcile_stores_reconnect_task_in_background_tasks(
    monkeypatch, global_cfg
) -> None:
    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())

    async def fake_list_running_db(conn):
        return [
            {"ws_id": "alice-app", "host_port": 12345, "host_name": "", "login": "alice"}
        ]

    monkeypatch.setattr(service_mod, "list_running_db", fake_list_running_db)

    started = asyncio.Event()
    release = asyncio.Event()
    ran: list[tuple[str, str]] = []

    async def fake_reconnect_workspace(self, ws_id: str, login: str) -> None:
        started.set()
        await release.wait()
        ran.append((ws_id, login))

    monkeypatch.setattr(
        service_mod.DevPodService, "_reconnect_workspace", fake_reconnect_workspace
    )

    svc = service_mod.DevPodService(global_cfg=global_cfg)

    task_holder: dict[str, asyncio.Task] = {}
    real_create_task = asyncio.create_task

    def spy_create_task(coro, *a, **kw):
        t = real_create_task(coro, *a, **kw)
        task_holder["task"] = t
        return t

    monkeypatch.setattr(service_mod.asyncio, "create_task", spy_create_task)

    # _devpod_state_exists("alice-app", "alice") retourne False naturellement :
    # tmp_data_root (via global_cfg) ne contient aucun état devpod pour "alice".
    reconcile_task = asyncio.create_task(svc.reconcile_port_forwards())
    await started.wait()

    # Pendant que la task de reconnexion est en plein vol (suspendue sur
    # release.wait()), elle doit être référencée par le service — pas seulement
    # schedulée puis oubliée (bug 036).
    assert task_holder["task"] in svc._background_tasks

    release.set()
    await task_holder["task"]
    await reconcile_task

    assert ran == [("alice-app", "alice")]
    # add_done_callback(discard) l'a retirée une fois terminée.
    assert task_holder["task"] not in svc._background_tasks
