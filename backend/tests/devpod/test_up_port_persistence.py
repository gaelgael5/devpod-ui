"""Bug 001 — collision d'allocation de ports openvscode.

Deux fenêtres fermées par le correctif, testées ici sans DB (status_store) :

1. Persistance dès l'allocation : le statut « provisioning » écrit par up()
   porte le host_port alloué — la colonne ne repasse jamais à NULL pendant le
   devpod up (jusqu'à 30 min), donc _used_ports() protège le port même si
   _reserved (mémoire volatile) est perdu (restart, _reset_service).
2. Réutilisation au re-up : si la ligne workspace_status possède déjà un
   host_port, up() le reprend au lieu d'en réallouer un — supprime la
   réallocation en rafale à la réconciliation, déclencheur principal observé.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


def _make_global_cfg(tmp_data_root):
    """GlobalConfig minimal, peuplé directement dans le cache module-level."""
    from portal.config.models import GlobalConfig

    return GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {
                "listen": "0.0.0.0:8080",
                "base_domain": "dev.yoops.org",
                "external_url": "https://dev.yoops.org",
                "dev_mode": True,
            },
            "auth": {
                "oidc": {
                    "issuer": "https://kc.test",
                    "client_id": "portal",
                    "client_secret": "",
                }
            },
            "secrets": {"backend": "inline"},
            "devpod": {
                "binary": "devpod",
                "client_cert_path": str(tmp_data_root / "certs" / "portal"),
            },
            "hosts": [
                {
                    "name": "local",
                    "default": True,
                    "type": "docker-tls",
                    "docker_host": "tcp://192.168.1.50:2376",
                    "address": "",
                }
            ],
            "caddy": {"admin_api": "http://caddy:2019"},
        }
    )


class _FakeExposure:
    def __init__(self, next_port: int = 41000) -> None:
        self.next_port = next_port
        self.allocate_calls: list[str] = []
        self.released: list[int] = []

    async def allocate_port(self, ws_id: str) -> int:
        self.allocate_calls.append(ws_id)
        return self.next_port

    async def release_port(self, port: int) -> None:
        self.released.append(port)

    async def allocate_ssh_port(self, ws_id: str) -> int:
        return self.next_port + 10000

    async def release_ssh_port(self, port: int) -> None:
        self.released.append(port)

    async def expose(self, ws_id: str, node_ip: str, host_port: int, **kwargs: Any) -> str:
        return f"https://ws-{ws_id}.dev.yoops.org"

    async def unexpose(self, ws_id: str) -> None:
        return None


def _setup_service(tmp_data_root, fake_devpod_bin, monkeypatch, exposure):
    import portal.devpod.service as service_mod
    from portal.db.global_config import set_cached_global
    from portal.devpod.service import DevPodService

    global_cfg = _make_global_cfg(tmp_data_root)
    set_cached_global(global_cfg)
    monkeypatch.setattr(service_mod, "ensure_provider", AsyncMock(return_value="docker"))
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin, exposure=exposure)
    monkeypatch.setattr(svc, "_start_port_forward", AsyncMock())
    return svc


async def test_up_persists_port_with_provisioning_status(
    status_store: dict[str, dict[str, Any]],
    tmp_data_root,
    fake_devpod_bin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le statut provisioning porte le host_port alloué — jamais NULL en DB."""
    import portal.devpod.service as service_mod
    from portal.config.models import WorkspaceSpec

    exposure = _FakeExposure(next_port=41000)
    svc = _setup_service(tmp_data_root, fake_devpod_bin, monkeypatch, exposure)

    subprocess_entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_subprocess(
        cmd: Any, env: Any, log_path: Any, ws_id: str, timeout_s: Any = None
    ) -> int:
        subprocess_entered.set()
        await release.wait()
        return 0

    monkeypatch.setattr(service_mod, "run_subprocess", fake_run_subprocess)

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")
    ws_id = await svc.up(login="alice", ws_spec=ws)
    await asyncio.wait_for(subprocess_entered.wait(), timeout=2.0)

    # Fenêtre 1 : pendant tout le devpod up, la ligne provisioning garde le port
    assert status_store[ws_id]["status"] == "provisioning"
    assert status_store[ws_id]["host_port"] == 41000

    release.set()
    await svc._up_tasks[ws_id]
    assert status_store[ws_id]["status"] == "running"
    assert status_store[ws_id]["host_port"] == 41000


async def test_up_reuses_persisted_port_instead_of_reallocating(
    status_store: dict[str, dict[str, Any]],
    tmp_data_root,
    fake_devpod_bin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-up d'un workspace connu : le host_port persisté est repris tel quel
    (reconnexion, réconciliation au démarrage) — aucune réallocation."""
    import portal.devpod.service as service_mod
    from portal.config.models import WorkspaceSpec

    exposure = _FakeExposure(next_port=41000)
    svc = _setup_service(tmp_data_root, fake_devpod_bin, monkeypatch, exposure)
    monkeypatch.setattr(service_mod, "run_subprocess", AsyncMock(return_value=0))

    status_store["alice-myapp"] = {
        "ws_id": "alice-myapp",
        "status": "running",
        "login": "alice",
        "host_port": 42123,
    }

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")
    ws_id = await svc.up(login="alice", ws_spec=ws)
    await svc._up_tasks[ws_id]

    assert exposure.allocate_calls == [], "pas de réallocation quand un port est persisté"
    assert status_store[ws_id]["host_port"] == 42123
    assert status_store[ws_id]["status"] == "running"


async def test_up_reallocates_when_persisted_port_is_duplicated(
    status_store: dict[str, dict[str, Any]],
    tmp_data_root,
    fake_devpod_bin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doublon hérité de l'ancienne allocation (deux workspaces persistés avec le
    même port, cas admin-rag/admin-devpod tous deux sur 40000) : le re-up ne doit
    PAS réutiliser le port dupliqué — il réalloue et assainit sa ligne."""
    import portal.devpod.service as service_mod
    from portal.config.models import WorkspaceSpec

    exposure = _FakeExposure(next_port=40001)
    svc = _setup_service(tmp_data_root, fake_devpod_bin, monkeypatch, exposure)
    monkeypatch.setattr(service_mod, "run_subprocess", AsyncMock(return_value=0))

    status_store["alice-rag"] = {
        "ws_id": "alice-rag",
        "status": "running",
        "login": "alice",
        "host_port": 40000,
    }
    status_store["alice-myapp"] = {
        "ws_id": "alice-myapp",
        "status": "stopped",
        "login": "alice",
        "host_port": 40000,  # doublon avec alice-rag
    }

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")
    ws_id = await svc.up(login="alice", ws_spec=ws)
    await svc._up_tasks[ws_id]

    assert exposure.allocate_calls == [ws_id], "le port dupliqué ne doit pas être réutilisé"
    assert status_store[ws_id]["host_port"] == 40001
    assert status_store["alice-rag"]["host_port"] == 40000  # l'autre ligne est intacte
