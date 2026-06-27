from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_ensure_workspace_ssh_key_generates_valid_ed25519(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key

    pub_key = ensure_workspace_ssh_key("alice", "myapp")

    assert pub_key.startswith("ssh-ed25519 ")
    assert pub_key.endswith(" devpod:alice/myapp")
    key_dir = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp"
    assert (key_dir / "id_ed25519").exists()
    assert (key_dir / "id_ed25519.pub").exists()
    assert pub_key == (key_dir / "id_ed25519.pub").read_text(encoding="utf-8").strip()


def test_ensure_workspace_ssh_key_private_key_has_600_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permissions not applicable on Windows")

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key

    ensure_workspace_ssh_key("alice", "myapp")

    import stat

    priv_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519"
    assert stat.S_IMODE(priv_path.stat().st_mode) == 0o600


def test_ensure_workspace_ssh_key_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key

    pub1 = ensure_workspace_ssh_key("alice", "myapp")
    pub2 = ensure_workspace_ssh_key("alice", "myapp")

    assert pub1 == pub2


def test_ensure_workspace_ssh_key_different_workspaces_get_different_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key

    pub_a = ensure_workspace_ssh_key("alice", "myapp")
    pub_b = ensure_workspace_ssh_key("alice", "otherapp")

    assert pub_a != pub_b
