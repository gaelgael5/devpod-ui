"""Bug 039 : up() doit déporter la génération du devcontainer (mkdtemp/copytree/
write_text, bloquants) via asyncio.to_thread — jamais dans l'event loop."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _make_global_cfg(tmp_data_root):
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
async def test_up_deports_write_devcontainer_via_to_thread(
    tmp_data_root, fake_devpod_bin, monkeypatch
) -> None:
    import portal.devpod.service as service_mod
    from portal.config.models import WorkspaceSpec
    from portal.db.global_config import set_cached_global
    from portal.devpod.service import DevPodService

    global_cfg = _make_global_cfg(tmp_data_root)
    set_cached_global(global_cfg)

    monkeypatch.setattr(service_mod, "ensure_provider", AsyncMock(return_value="docker"))

    calls: list[object] = []
    real_to_thread = service_mod.asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(service_mod.asyncio, "to_thread", spy_to_thread)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    # Interrompt juste après _write_devcontainer (pas besoin d'aller jusqu'au
    # bout de up() pour ce test — seule la déportation de l'I/O nous intéresse).
    class _StopHere(Exception):
        pass

    async def fake_write_status(*args, **kwargs):
        raise _StopHere

    monkeypatch.setattr(svc, "_write_status", fake_write_status)

    ws = WorkspaceSpec(
        name="myapp",
        source="git@github.com:user/repo.git",
        recipe_volumes=["dummy"],  # force needs_devcontainer=True
    )

    with pytest.raises(_StopHere):
        await svc.up(login="alice", ws_spec=ws)

    assert svc._write_devcontainer in calls
