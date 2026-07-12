"""Bug 037 : un port alloué par up() (allocate_port) doit être relâché si une
exception survient avant que la task de fond (_run_up_task) ne soit créée —
sinon le port reste réservé en mémoire jusqu'au restart du portail."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _make_global_cfg(tmp_data_root):
    """GlobalConfig minimal avec un host docker-tls par défaut.

    Construit directement (pas via config.yaml + load_global()) : up() lit
    load_global() depuis le cache module-level de db/global_config.py, qu'on
    peuple nous-même via set_cached_global — indépendant de tout warm depuis
    une vraie DB.
    """
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


@pytest.mark.asyncio
async def test_up_releases_port_when_write_devcontainer_fails(
    status_store, tmp_data_root, fake_devpod_bin, monkeypatch
) -> None:
    # status_store : depuis le bug 001, up() lit la ligne workspace_status
    # (réutilisation de port) avant l'allocation — la couche DB doit être mockée.
    import portal.devpod.service as service_mod
    from portal.config.models import WorkspaceSpec
    from portal.db.global_config import set_cached_global
    from portal.devpod.service import DevPodService

    global_cfg = _make_global_cfg(tmp_data_root)
    set_cached_global(global_cfg)

    monkeypatch.setattr(service_mod, "ensure_provider", AsyncMock(return_value="docker"))

    class _FakeExposure:
        def __init__(self) -> None:
            self.released: list[int] = []

        async def allocate_port(self, ws_id: str) -> int:
            return 41000

        async def release_port(self, port: int) -> None:
            self.released.append(port)

    exposure = _FakeExposure()
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin, exposure=exposure)

    def boom(*args, **kwargs):
        raise RuntimeError("devcontainer write failed")

    monkeypatch.setattr(svc, "_write_devcontainer", boom)

    ws = WorkspaceSpec(
        name="myapp",
        source="git@github.com:user/repo.git",
        recipe_volumes=["dummy"],  # force needs_devcontainer=True → _write_devcontainer appelé
    )

    with pytest.raises(RuntimeError, match="devcontainer write failed"):
        await svc.up(login="alice", ws_spec=ws)

    assert exposure.released == [41000]
