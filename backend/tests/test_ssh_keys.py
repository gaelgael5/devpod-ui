from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest


def test_generate_git_credential_ssh_key_creates_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, public_key = generate_git_credential_ssh_key("alice", "my-key")

    priv = Path(key_path)
    pub = priv.parent / "id_ed25519.pub"
    assert priv.exists()
    assert pub.exists()
    assert public_key.startswith("ssh-ed25519 ")
    assert "devpod-git:alice/my-key" in public_key


def test_generate_git_credential_ssh_key_private_key_has_600_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permissions not applicable on Windows")

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, _ = generate_git_credential_ssh_key("alice", "my-key")
    priv_path = Path(key_path)
    assert stat.S_IMODE(priv_path.stat().st_mode) == 0o600


def test_generate_git_credential_ssh_key_public_key_has_644_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permissions not applicable on Windows")

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, _ = generate_git_credential_ssh_key("alice", "my-key")
    pub_path = Path(key_path).parent / "id_ed25519.pub"
    assert stat.S_IMODE(pub_path.stat().st_mode) == 0o644


def test_generate_git_credential_ssh_key_returns_consistent_pub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, public_key = generate_git_credential_ssh_key("alice", "my-key")
    pub_file = (Path(key_path).parent / "id_ed25519.pub").read_text(encoding="utf-8").strip()
    assert pub_file == public_key.strip()


def test_derive_git_credential_public_key_reads_existing_pub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import derive_git_credential_public_key, generate_git_credential_ssh_key

    key_path, original_pub = generate_git_credential_ssh_key("alice", "my-key")
    derived = derive_git_credential_public_key(key_path)
    assert derived.strip() == original_pub.strip()


def test_derive_git_credential_public_key_recreates_missing_pub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import derive_git_credential_public_key, generate_git_credential_ssh_key

    key_path, _ = generate_git_credential_ssh_key("alice", "my-key")
    pub_path = Path(key_path).parent / "id_ed25519.pub"
    pub_path.unlink()

    derived = derive_git_credential_public_key(key_path)

    assert derived.startswith("ssh-ed25519 ")
    assert pub_path.exists()


def test_derive_git_credential_public_key_public_key_has_644_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permissions not applicable on Windows")

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None

    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")

    from portal.ssh_keys import derive_git_credential_public_key, generate_git_credential_ssh_key

    key_path, _ = generate_git_credential_ssh_key("alice", "my-key")
    pub_path = Path(key_path).parent / "id_ed25519.pub"
    pub_path.unlink()

    derive_git_credential_public_key(key_path)

    assert stat.S_IMODE(pub_path.stat().st_mode) == 0o644
