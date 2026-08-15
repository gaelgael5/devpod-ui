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


def test_tmux_attach_reaches_portal_sessions() -> None:
    """La ForceCommand doit rendre les sessions du PORTAIL disponibles côté Termix :
    attache la session existante la plus récente (`attach-session` sans -t), et ne
    crée `main` qu'à défaut — sinon une connexion Termix atterrit toujours dans une
    session `main` vide alors qu'une session portail est ouverte à côté."""
    from portal.wscomponents.registry import SSH_ACCESS

    attach = next(f for f in SSH_ACCESS.files if f.path == "/usr/local/bin/ws-tmux-attach")
    body = attach.content
    assert "attach-session" in body
    assert "new-session -A -s main" in body  # fallback : aucune session existante
    # L'attache réussie ne doit PAS retomber sur la création de main (exit après).
    assert body.index("attach-session") < body.index("new-session")


def test_tmux_attach_refresh_cmd_is_gated_and_idempotent() -> None:
    """Commande de rafraîchissement au `up` (spec 35b) : ne touche que les
    workspaces T1 (script déjà présent), compare avant d'écrire, root ou sudo."""
    from portal.wscomponents.registry import SSH_ACCESS, tmux_attach_refresh_cmd

    cmd = tmux_attach_refresh_cmd()
    assert "ws-tmux-attach" in cmd
    assert "base64 -d" in cmd
    assert "cmp -s" in cmd  # idempotent : réécrit seulement si le contenu diffère
    assert "sudo -n" in cmd and 'id -u' in cmd  # conteneurs root sans sudo
    # Le contenu embarqué est bien le script courant du composant.
    import base64

    attach = next(f for f in SSH_ACCESS.files if f.path == "/usr/local/bin/ws-tmux-attach")
    b64 = base64.b64encode(attach.content.encode()).decode()
    assert b64 in cmd


def test_authorized_keys_refresh_cmd_is_gated_and_idempotent() -> None:
    """Refresh de la clé SSH au `up` : ne touche que les workspaces T1 (gate sur le
    sshd_config du composant), compare avant d'écrire, embarque la clé courante —
    une image prebuild en cache ne doit plus laisser une clé périmée après un
    delete/recreate (auth bastion/Termix KO sinon)."""
    from portal.wscomponents.registry import authorized_keys_refresh_cmd

    pubkey = "ssh-ed25519 AAAATEST ws:admin-demo"
    cmd = authorized_keys_refresh_cmd(pubkey)
    assert "/etc/ssh/sshd_config.d/10-portal.conf" in cmd  # gate T1
    assert "base64 -d" in cmd
    assert "cmp -s" in cmd  # idempotent : réécrit seulement si le contenu diffère
    assert "authorized_keys" in cmd and "install -m 600" in cmd
    # Le contenu embarqué est bien la clé passée, terminée par un newline.
    import base64

    b64 = base64.b64encode(f"{pubkey}\n".encode()).decode()
    assert b64 in cmd


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
