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


async def test_reconcile_stores_reconnect_task_in_background_tasks(monkeypatch, global_cfg) -> None:
    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())

    async def fake_list_running_db(conn):
        return [{"ws_id": "alice-app", "host_port": 12345, "host_name": "", "login": "alice"}]

    monkeypatch.setattr(service_mod, "list_running_db", fake_list_running_db)

    started = asyncio.Event()
    release = asyncio.Event()
    ran: list[tuple[str, str]] = []

    async def fake_reconnect_workspace(self, ws_id: str, login: str) -> None:
        started.set()
        await release.wait()
        ran.append((ws_id, login))

    monkeypatch.setattr(service_mod.DevPodService, "_reconnect_workspace", fake_reconnect_workspace)

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


async def test_reconcile_relaunches_tunnel_when_client_state_is_present(
    monkeypatch, global_cfg, tmp_data_root
) -> None:
    """État devpod client présent → on relance le tunnel, PAS un `devpod up`.

    C'est la branche saine (`reconcile_port_forward`), celle qui n'apparaissait
    jamais dans les logs tant que `_devpod_state_exists` cherchait sous `agent/`.
    Elle vaut d'être verrouillée : sa régression est silencieuse — tout continue
    de « marcher », au prix d'un up complet par redémarrage du portail.
    """
    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())
    # reconcile_port_forwards relit la config globale (load_global), il ne se
    # contente pas de celle injectée au service.
    monkeypatch.setattr(service_mod, "load_global", lambda: global_cfg)

    async def fake_list_running_db(conn):
        return [{"ws_id": "alice-app", "host_port": 12345, "host_name": "local", "login": "alice"}]

    monkeypatch.setattr(service_mod, "list_running_db", fake_list_running_db)

    # L'état client, à l'endroit où devpod le range réellement.
    state = (
        tmp_data_root
        / "users"
        / "alice"
        / "devpod"
        / "contexts"
        / service_mod.DEVPOD_CONTEXT
        / "workspaces"
        / "alice-app"
    )
    state.mkdir(parents=True)

    reconnected: list[str] = []

    async def fake_reconnect_workspace(self, ws_id: str, login: str) -> None:
        reconnected.append(ws_id)

    forwarded: list[tuple[str, int]] = []

    async def fake_start_port_forward(self, ws_id: str, env, host_port: int) -> None:
        forwarded.append((ws_id, host_port))

    monkeypatch.setattr(service_mod.DevPodService, "_reconnect_workspace", fake_reconnect_workspace)
    monkeypatch.setattr(service_mod.DevPodService, "_start_port_forward", fake_start_port_forward)

    svc = service_mod.DevPodService(global_cfg=global_cfg)
    await svc.reconcile_port_forwards()

    assert forwarded == [("alice-app", 12345)]
    assert reconnected == []
