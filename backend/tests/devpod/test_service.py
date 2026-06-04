from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_up_rejects_non_dns_safe_name(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() rejette un ws name non DNS-safe avant tout lancement."""
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    # WorkspaceSpec.name est validé par pydantic — on teste via _ws_id directement
    with pytest.raises(ValueError, match="DNS"):
        svc._ws_id("alice", "INVALID NAME!")


@pytest.mark.asyncio
async def test_up_writes_status_file(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() écrit un fichier de statut dans routes/<ws_id>.json."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")

    ws_id = await svc.up(login="alice", ws_spec=ws)
    assert ws_id == "alice-myapp"

    # Attendre que la tâche de fond passe de "provisioning" à "running"/"failed"
    # On sonde jusqu'à 10s pour absorber l'overhead subprocess Windows.
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break
    else:
        pytest.fail(f"Status file never reached running/failed (last: {status_path.read_text()})")

    assert status_path.exists(), f"Status file not found: {status_path}"
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["ws_id"] == ws_id
    assert data["status"] in ("running", "failed")


@pytest.mark.asyncio
async def test_secrets_not_leaked_in_logs(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """Les env vars passées à up() ne doivent pas apparaître dans les logs."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(
        name="myapp",
        source="git@github.com:user/repo.git",
        env={"API_KEY": "SUPER_SECRET_VALUE"},
    )

    ws_id = await svc.up(login="alice", ws_spec=ws)

    # Attendre que la tâche de fond termine avant de vérifier les logs
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break

    log_path = tmp_data_root / "logs" / "alice" / f"{ws_id}.log"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
        assert "SUPER_SECRET_VALUE" not in content, "Secret leaked in logs!"


@pytest.mark.asyncio
async def test_status_returns_current_status(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """status() lit le fichier de statut et retourne l'état courant."""
    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws_id = "alice-myapp"

    routes_dir = tmp_data_root / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / f"{ws_id}.json").write_text(
        json.dumps({"ws_id": ws_id, "status": "running"}), encoding="utf-8"
    )

    status = await svc.status(login="alice", ws_id=ws_id)
    assert status["status"] == "running"
