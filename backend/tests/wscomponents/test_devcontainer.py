"""Injection des composants système dans le devcontainer (spec 18 T1, brique 3A)."""

from __future__ import annotations

from pathlib import Path

from portal.wscomponents.devcontainer import inject_components


def test_inject_adds_feature_runargs_poststart(tmp_path: Path) -> None:
    content: dict = {"image": "base", "runArgs": ["--memory=2g"]}
    inject_components(
        content,
        tmp_path,
        {"ssh_port": "50123", "ssh_pubkey": "ssh-ed25519 K", "ws_user": "vscode"},
    )

    # Feature ssh-access référencée + dossier écrit.
    assert "./ssh-access" in content["features"]
    assert (tmp_path / "ssh-access" / "install.sh").exists()
    # runArgs : --memory conservé + --publish ajouté (pas d'écrasement).
    assert "--memory=2g" in content["runArgs"]
    assert "--publish" in content["runArgs"] and "0.0.0.0:50123:22" in content["runArgs"]
    # postStartCommand : sshd démarré.
    assert "sshd" in content["postStartCommand"]


def test_inject_preserves_existing_poststart(tmp_path: Path) -> None:
    content: dict = {"image": "base", "postStartCommand": "echo hi"}
    inject_components(
        content, tmp_path, {"ssh_port": "50000", "ssh_pubkey": "k", "ws_user": "vscode"}
    )
    assert content["postStartCommand"].startswith("echo hi && ")
    assert "sshd" in content["postStartCommand"]


def test_inject_no_components_is_noop(tmp_path: Path) -> None:
    content: dict = {"image": "base"}
    inject_components(content, tmp_path, {}, components=[])
    assert "features" not in content and "runArgs" not in content
