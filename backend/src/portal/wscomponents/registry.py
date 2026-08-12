"""Registre des composants système de workspace + tri topologique (spec 18 T1).

`ssh-access` (sshd durci + tmux) est le premier composant : il publie le port SSH
du workspace sur l'IP du node, pose la clé du workspace dans `authorized_keys` de
l'utilisateur du workspace, et force l'attache au socket tmux partagé — de sorte
que les sessions du portail et l'accès Termix soient le même serveur tmux.
"""

from __future__ import annotations

from .models import ComponentFile, WorkspaceComponent


class CycleError(RuntimeError):
    """Dépendance circulaire dans `installs_after`."""


# sshd durci : clé publique only, login restreint à l'utilisateur du workspace,
# aucun forwarding, ForceCommand → attache le socket tmux partagé.
_SSHD_CONFIG = """\
# Géré par le portail (composant ssh-access) — ne pas éditer.
Port 22
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers {ws_user}
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
ForceCommand /usr/local/bin/ws-tmux-attach
"""

# Détection du socket tmux (identique à devpod/exec.py) + attache/crée la session
# partagée. Fallback shell si tmux absent. Rend l'accès Termix cohérent avec les
# sessions du portail (même socket).
_TMUX_ATTACH = """\
#!/bin/sh
TMUX_SOCK=$(find /tmp -maxdepth 2 -name default -path '*/tmux-*/*' 2>/dev/null | head -1)
if command -v tmux >/dev/null 2>&1; then
  exec tmux ${TMUX_SOCK:+-S "$TMUX_SOCK"} new-session -A -s main
fi
echo '[portal] tmux absent'; exec bash -l
"""

SSH_ACCESS = WorkspaceComponent(
    name="ssh-access",
    packages=["openssh-server", "tmux"],
    files=[
        ComponentFile(path="/etc/ssh/sshd_config.d/10-portal.conf", content=_SSHD_CONFIG),
        ComponentFile(path="/usr/local/bin/ws-tmux-attach", content=_TMUX_ATTACH, mode="0755"),
        ComponentFile(
            path="/home/{ws_user}/.ssh/authorized_keys",
            content="{ssh_pubkey}\n",
            mode="0600",
            owner="{ws_user}",
        ),
    ],
    # postStartCommand tourne en tant qu'utilisateur du conteneur (vscode) ; sshd
    # exige root (lire les host keys 600, binder le port) → `sudo` (l'image de base
    # devcontainer accorde le sudo sans mot de passe). /run/sshd = priv-sep dir ;
    # sshd daemonisé (pas -D : postStart ne doit pas bloquer).
    post_start=["sudo mkdir -p /run/sshd", "sudo ssh-keygen -A", "sudo /usr/sbin/sshd"],
    run_args=["--publish", "0.0.0.0:{ssh_port}:22"],
)


# Registre des composants toujours injectés par le portail (ordre par installs_after).
SYSTEM_COMPONENTS: list[WorkspaceComponent] = [SSH_ACCESS]


def get_component(name: str) -> WorkspaceComponent | None:
    """Composant du registre par nom, ou None."""
    return next((c for c in SYSTEM_COMPONENTS if c.name == name), None)


def ordered_components(
    components: list[WorkspaceComponent] | None = None,
) -> list[WorkspaceComponent]:
    """Composants actifs, triés topologiquement sur `installs_after` (Kahn).

    `components` par défaut = `SYSTEM_COMPONENTS`. Les composants désactivés sont
    exclus ; une dépendance absente du lot est ignorée (pas d'arête). Lève
    `CycleError` sur cycle.
    """
    source = SYSTEM_COMPONENTS if components is None else components
    comps = [c for c in source if c.enabled]
    present = {c.name for c in comps}
    by_name = {c.name: c for c in comps}
    # Arêtes uniquement vers des dépendances présentes et actives.
    deps = {c.name: {d for d in c.installs_after if d in present} for c in comps}
    indeg = {name: len(d) for name, d in deps.items()}
    ready = sorted(n for n, d in indeg.items() if d == 0)
    out: list[WorkspaceComponent] = []
    while ready:
        name = ready.pop(0)
        out.append(by_name[name])
        for other, d in deps.items():
            if name in d:
                indeg[other] -= 1
                if indeg[other] == 0:
                    ready.append(other)
                    ready.sort()
    if len(out) != len(comps):
        raise CycleError(f"cycle dans installs_after parmi {sorted(present)}")
    return out
