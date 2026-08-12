"""Registre de composants système de workspace (spec 18 T1, brique 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.wscomponents.models import WorkspaceComponent, render
from portal.wscomponents.registry import (
    CycleError,
    get_component,
    ordered_components,
)


def _c(name: str, **over: object) -> WorkspaceComponent:
    return WorkspaceComponent(name=name, **over)  # type: ignore[arg-type]


def test_component_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        WorkspaceComponent(name="x", unknown=1)  # type: ignore[call-arg]


def test_topological_order() -> None:
    comps = [_c("b", installs_after=["a"]), _c("a"), _c("c", installs_after=["b"])]
    names = [c.name for c in ordered_components(comps)]
    assert names.index("a") < names.index("b") < names.index("c")


def test_cycle_detected() -> None:
    comps = [_c("a", installs_after=["b"]), _c("b", installs_after=["a"])]
    with pytest.raises(CycleError):
        ordered_components(comps)


def test_disabled_excluded() -> None:
    comps = [_c("a"), _c("b", enabled=False)]
    assert [c.name for c in ordered_components(comps)] == ["a"]


def test_render_substitutes_placeholders() -> None:
    comp = WorkspaceComponent(
        name="t",
        packages=["openssh-server"],
        run_args=["--publish", "0.0.0.0:{ssh_port}:22"],
        post_start=["echo {ws_user}"],
        files=[
            {
                "path": "/home/{ws_user}/.ssh/authorized_keys",
                "content": "{ssh_pubkey}",
                "mode": "0600",
                "owner": "{ws_user}",
            }
        ],
    )
    r = render(comp, {"ssh_port": "51000", "ssh_pubkey": "ssh-ed25519 AAA", "ws_user": "vscode"})
    assert r.run_args == ["--publish", "0.0.0.0:51000:22"]
    assert r.post_start == ["echo vscode"]
    f = r.files[0]
    assert f.path == "/home/vscode/.ssh/authorized_keys"
    assert f.content == "ssh-ed25519 AAA"
    assert f.owner == "vscode" and f.mode == "0600"


# ─── Composant ssh-access ──────────────────────────────────────────────────────


def test_ssh_access_registered_and_enabled() -> None:
    ssh = get_component("ssh-access")
    assert ssh is not None and ssh.enabled is True


def test_ssh_access_render_publishes_port_and_places_key() -> None:
    ssh = get_component("ssh-access")
    assert ssh is not None
    r = render(
        ssh,
        {"ssh_port": "50123", "ssh_pubkey": "ssh-ed25519 KEYDATA ws:x", "ws_user": "vscode"},
    )
    # Port publié sur l'IP du node.
    assert "--publish" in r.run_args and "0.0.0.0:50123:22" in r.run_args
    # openssh + tmux installés par le composant.
    assert "openssh-server" in r.packages and "tmux" in r.packages
    # Clé du workspace dans authorized_keys de l'utilisateur du workspace.
    ak = next(f for f in r.files if f.path.endswith("/.ssh/authorized_keys"))
    assert ak.content.strip() == "ssh-ed25519 KEYDATA ws:x"
    assert ak.owner == "vscode" and ak.mode == "0600"
    # sshd durci : login = user du workspace, ForceCommand attache tmux.
    sshd = next(f for f in r.files if "sshd_config" in f.path)
    assert "AllowUsers vscode" in sshd.content
    assert "ForceCommand" in sshd.content
    assert "PasswordAuthentication no" in sshd.content
    assert "PermitRootLogin no" in sshd.content
    # sshd démarré (daemonisé, pas -D bloquant) au postStart, /run/sshd créé avant.
    assert any("/usr/sbin/sshd" in c for c in r.post_start)
    assert any("/run/sshd" in c for c in r.post_start)
    assert not any("sshd -D" in c for c in r.post_start)
