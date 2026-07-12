# backend/tests/devpod/test_stop.py
"""stop() ne doit jamais écrire "stopped" si `devpod stop` a échoué.

Sinon la DB/UI affiche "arrêté" alors que le conteneur peut encore tourner —
l'exposition (tunnel + route Caddy) est déjà retirée avant l'appel, donc le
workspace redevient inaccessible sans qu'on sache s'il tourne toujours (bug 006).
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_stop_writes_unknown_status_when_devpod_stop_fails(
    monkeypatch: pytest.MonkeyPatch, global_cfg, fake_devpod_bin: list[str], db_engine
) -> None:
    import portal.devpod.service as service_mod
    from portal.devpod.service import DevPodService

    async def fake_run_subprocess(**kwargs: object) -> int:
        return 1

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    await svc._write_status("alice-app", "running", login="alice")

    await svc.stop("alice", "alice-app")

    status = await svc.status("alice", "alice-app")
    assert status["status"] == "unknown"


@pytest.mark.asyncio
async def test_stop_writes_stopped_status_on_success(
    global_cfg, fake_devpod_bin: list[str], db_engine
) -> None:
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    await svc._write_status("alice-app", "running", login="alice")

    await svc.stop("alice", "alice-app")

    status = await svc.status("alice", "alice-app")
    assert status["status"] == "stopped"
