"""Matérialisation d'un composant rendu en Feature devcontainer (spec 18 T1, brique 3A)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from portal.wscomponents.materialize import write_feature
from portal.wscomponents.models import render
from portal.wscomponents.registry import get_component


def _decode_file_from_install(install: str, marker_path: str) -> str:
    """Retrouve la ligne `... base64 -d > <marker_path>` et décode le b64 injecté."""
    for line in install.splitlines():
        if f"> {marker_path}" in line or f"> '{marker_path}'" in line:
            b64 = line.split("printf '%s' ", 1)[1].split(" |", 1)[0].strip().strip("'")
            return base64.b64decode(b64).decode()
    raise AssertionError(f"aucune écriture pour {marker_path} dans install.sh")


def test_write_feature_creates_dir_and_install(tmp_path: Path) -> None:
    ssh = get_component("ssh-access")
    assert ssh is not None
    r = render(
        ssh, {"ssh_port": "50123", "ssh_pubkey": "ssh-ed25519 KEY ws:x", "ws_user": "vscode"}
    )

    name = write_feature(r, tmp_path)
    assert name == "ssh-access"
    feat = tmp_path / "ssh-access"
    fj = json.loads((feat / "devcontainer-feature.json").read_text())
    assert fj["id"] == "ssh-access"
    install = (feat / "install.sh").read_text()

    # Paquets installés.
    assert "apt-get install -y" in install
    assert "openssh-server" in install and "tmux" in install
    # authorized_keys écrit (b64) avec la clé, perms + owner.
    ak = _decode_file_from_install(install, "/home/vscode/.ssh/authorized_keys")
    assert ak.strip() == "ssh-ed25519 KEY ws:x"
    assert "chmod 0600 /home/vscode/.ssh/authorized_keys" in install
    assert "chown vscode /home/vscode/.ssh/authorized_keys" in install
    # sshd_config durci écrit.
    sshd = _decode_file_from_install(install, "/etc/ssh/sshd_config.d/10-portal.conf")
    assert "AllowUsers vscode" in sshd and "ForceCommand" in sshd


def test_write_feature_content_roundtrips_arbitrary_bytes(tmp_path: Path) -> None:
    from portal.wscomponents.models import ComponentFile, WorkspaceComponent

    tricky = "line1\n'quotes' $VAR `bt` \"dq\"\nEOF\n#!/bin/sh"
    comp = WorkspaceComponent(
        name="c", files=[ComponentFile(path="/x/y.conf", content=tricky)]
    )
    write_feature(render(comp, {}), tmp_path)
    install = (tmp_path / "c" / "install.sh").read_text()
    assert _decode_file_from_install(install, "/x/y.conf") == tricky
