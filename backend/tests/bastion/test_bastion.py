"""Bastion : génération de clés + gestion de authorized_keys (anti-injection, atomique)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from portal.bastion import authorized_keys as ak
from portal.bastion.keys import generate_keypair


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    return tmp_path


def test_generate_keypair_openssh() -> None:
    priv, pub = generate_keypair(comment="ws:admin-doc")
    assert priv.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert pub.startswith("ssh-ed25519 ") and pub.endswith("ws:admin-doc")


@pytest.mark.asyncio
async def test_set_and_remove_entry(data_root: Path) -> None:
    _, pub = generate_keypair()
    await ak.set_entry("admin", "admin-doc", pub)
    path = data_root / "bastion" / "authorized_keys"
    line = path.read_text().strip()
    assert line.startswith('command="/usr/local/bin/ws-bastion admin admin-doc"')
    assert "no-port-forwarding" in line and "no-pty" not in line  # pty conservé
    # Perms strictes (600 fichier, 700 dossier).
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700

    assert await ak.remove_entry("admin", "admin-doc") is True
    assert path.read_text() == ""
    assert await ak.remove_entry("admin", "admin-doc") is False  # idempotent


@pytest.mark.asyncio
async def test_set_entry_is_idempotent_per_ws(data_root: Path) -> None:
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    await ak.set_entry("admin", "admin-doc", pub1)
    await ak.set_entry("admin", "admin-doc", pub2)  # remplace, pas de doublon
    await ak.set_entry("admin", "admin-rag", pub1)  # autre ws → 2e ligne
    lines = (data_root / "bastion" / "authorized_keys").read_text().splitlines()
    assert len(lines) == 2
    assert any("admin-doc" in ln and pub2.split()[1] in ln for ln in lines)


@pytest.mark.asyncio
async def test_rejects_injection_in_login_or_ws_id(data_root: Path) -> None:
    _, pub = generate_keypair()
    for bad in ('admin";rm -rf /', "admin doc", "../evil", "admin\n"):
        with pytest.raises(ValueError):
            await ak.set_entry(bad, "admin-doc", pub)
        with pytest.raises(ValueError):
            await ak.set_entry("admin", bad, pub)


@pytest.mark.asyncio
async def test_rejects_bad_pubkey(data_root: Path) -> None:
    with pytest.raises(ValueError):
        await ak.set_entry("admin", "admin-doc", "not-a-key")
    with pytest.raises(ValueError):
        await ak.set_entry("admin", "admin-doc", "ssh-ed25519 AAAA\ninjected")
