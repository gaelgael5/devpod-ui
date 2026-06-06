from __future__ import annotations

import os
from pathlib import Path

import pytest


def _read_calls(devpod_home: str) -> list[str]:
    """Lit les appels enregistrés par fake_devpod."""
    log_path = Path(devpod_home) / "fake_calls.log"
    if not log_path.exists():
        return []
    return log_path.read_text(encoding="utf-8").strip().splitlines()


# ---------------------------------------------------------------------------
# Tests unitaires sur _parse_providers
# ---------------------------------------------------------------------------


def test_parse_providers_extracts_names_from_table() -> None:
    """_parse_providers extrait les noms exacts depuis le tableau tabulaire."""
    from portal.devpod.provider import _parse_providers

    table = """\
    NAME   | VERSION | DEFAULT |
  ---------+---------+---------+
   docker  | v0.0.1  | true    |
   ssh     | v0.0.15 | false   |
"""
    providers = _parse_providers(table)
    assert "docker" in providers
    assert "ssh" in providers
    assert "docker-compose" not in providers


def test_parse_providers_empty_table() -> None:
    """_parse_providers retourne un set vide sur tableau sans données."""
    from portal.devpod.provider import _parse_providers

    table = """\
    NAME | VERSION | DEFAULT |
  -------+---------+---------+
"""
    providers = _parse_providers(table)
    assert providers == set()


# ---------------------------------------------------------------------------
# Tests d'intégration avec fake_devpod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_provider_adds_docker_when_absent(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Si docker est absent, provider add docker doit être appelé."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    devpod_home = str(tmp_data_root / "users" / "alice" / "devpod")
    env = {
        "DEVPOD_HOME": devpod_home,
        "PATH": os.environ.get("PATH", ""),
    }

    await ensure_provider(
        login="alice", host_type="docker-tls", env=env, devpod_bin=fake_devpod_bin
    )

    calls = _read_calls(devpod_home)
    assert any("provider add docker" in c for c in calls), (
        f"Expected 'provider add docker', got: {calls}"
    )


@pytest.mark.asyncio
async def test_ensure_provider_is_idempotent_when_already_present(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Si docker est déjà présent, provider add ne doit PAS être appelé."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    # "provider_ok" dans le chemin → fake_devpod retourne docker dans le tableau
    devpod_home = str(tmp_data_root / "users" / "alice" / "provider_ok_devpod")
    os.makedirs(devpod_home, exist_ok=True)
    env = {
        "DEVPOD_HOME": devpod_home,
        "PATH": os.environ.get("PATH", ""),
    }

    await ensure_provider(
        login="alice", host_type="docker-tls", env=env, devpod_bin=fake_devpod_bin
    )

    calls = _read_calls(devpod_home)
    assert not any("provider add" in c for c in calls), f"Expected no 'provider add', got: {calls}"


@pytest.mark.asyncio
async def test_ensure_provider_uses_ssh_for_ssh_host(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Pour host ssh, provider add ssh doit être appelé (pas docker)."""
    from portal.config.store import ensure_user_dir
    from portal.devpod.provider import ensure_provider

    ensure_user_dir("alice")
    devpod_home = str(tmp_data_root / "users" / "alice" / "devpod_ssh")
    env = {
        "DEVPOD_HOME": devpod_home,
        "PATH": os.environ.get("PATH", ""),
    }

    await ensure_provider(login="alice", host_type="ssh", env=env, devpod_bin=fake_devpod_bin)

    calls = _read_calls(devpod_home)
    assert any("provider add ssh" in c for c in calls), f"Expected 'provider add ssh', got: {calls}"
    assert not any("provider add docker" in c for c in calls), (
        f"Unexpected 'provider add docker', got: {calls}"
    )
