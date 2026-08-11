"""Runtime du sshd bastion : setup /data/bastion + apply sans binaire sshd."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from portal.bastion import runtime as rt


def test_setup_dir_creates_perms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    rt.setup_dir()
    d = tmp_path / "bastion"
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    ak = d / "authorized_keys"
    assert ak.exists() and stat.S_IMODE(os.stat(ak).st_mode) == 0o600
    assert (d / "ssh_host_ed25519_key").exists()  # host key générée


def test_apply_noop_without_sshd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(rt, "_SSHD", "/nonexistent/sshd")
    rt.apply(True)  # binaire absent → ne démarre rien, ne crashe pas
    assert rt.is_running() is False
    rt.apply(False)  # arrêt idempotent
    assert rt.is_running() is False
