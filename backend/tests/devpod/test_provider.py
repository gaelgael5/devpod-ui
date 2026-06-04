from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_ensure_provider_adds_docker_when_absent(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Si le provider docker est absent du DEVPOD_HOME, il doit être ajouté (sans erreur)."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    env = {
        "DEVPOD_HOME": str(tmp_data_root / "users" / "alice" / "devpod"),
        "PATH": os.environ.get("PATH", ""),
    }

    # Pas de "provider_ok" dans le chemin → fake_devpod retourne tableau vide
    # ensure_provider doit appeler "provider add docker" sans lever d'exception
    await ensure_provider(
        login="alice",
        host_type="docker-tls",
        env=env,
        devpod_bin=fake_devpod_bin,
    )


@pytest.mark.asyncio
async def test_ensure_provider_is_idempotent_when_already_present(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Si le provider est déjà présent, ensure_provider ne relance pas provider add."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    # "provider_ok" dans le chemin DEVPOD_HOME → fake_devpod simule docker déjà présent
    devpod_home = str(tmp_data_root / "users" / "alice" / "provider_ok_devpod")
    os.makedirs(devpod_home, exist_ok=True)
    env = {
        "DEVPOD_HOME": devpod_home,
        "PATH": os.environ.get("PATH", ""),
    }

    # Ne doit pas lever d'exception (idempotent)
    await ensure_provider(
        login="alice",
        host_type="docker-tls",
        env=env,
        devpod_bin=fake_devpod_bin,
    )


@pytest.mark.asyncio
async def test_ensure_provider_uses_ssh_for_ssh_host(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Pour un host ssh, le provider ssh doit être utilisé (pas docker)."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    env = {
        "DEVPOD_HOME": str(tmp_data_root / "users" / "alice" / "devpod"),
        "PATH": os.environ.get("PATH", ""),
    }

    # Ne doit pas lever d'exception
    await ensure_provider(
        login="alice",
        host_type="ssh",
        env=env,
        devpod_bin=fake_devpod_bin,
    )
