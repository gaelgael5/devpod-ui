"""Logique de création d'une VM de test (host `usage=tests`).

Parties pures (mapping résultat → HostConfig, construction des args) ; l'exécution
SSH et la persistance vivent dans la route `/me`.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable

from ..config.models import HostConfig
from .exec import remote_tmux_command
from .name_mask import COUNT_MASK_RE

_VAR_RE = re.compile(r"<([^<>]+)>")
# Masque de numerotation : `{count++}` vaut le numero de la PROCHAINE machine du
# workspace, comme `<N+1>`. Les deux `+` sont ce qui le distingue d'un
# placeholder de script (`_SUBST_PLACEHOLDER_RE`, `\{[A-Za-z_]\w*\}`) : `{count}`
# seul en aurait la forme et creerait une ambiguite, on ne le reconnait donc pas.
_COUNT_MASK_RE = COUNT_MASK_RE


def substitute_param_vars(args: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    """Remplace les `<NOM>` dans chaque valeur par la variable correspondante.

    Les variables disponibles sont les autres args (par nom, ex. `<NEW_VMID>`) plus
    celles fournies dans `extra` (ex. `N`, `N+1`). Une variable inconnue est laissée
    telle quelle (pas d'erreur).

    Le masque `{count++}` est accepté comme synonyme de `<N+1>` : c'est la forme
    attendue pour numéroter un nom de machine (`Host-Test-{count++}`).
    """
    variables = {**args, **extra}

    def _repl(m: re.Match[str]) -> str:
        return variables.get(m.group(1), m.group(0))

    def _rendu(valeur: str) -> str:
        # Le masque d'abord : sa valeur est un nombre, qui ne peut pas contenir
        # de `<NOM>` a resoudre ensuite.
        suivant = extra.get("N+1")
        if suivant is not None:
            valeur = _COUNT_MASK_RE.sub(suivant, valeur)
        return _VAR_RE.sub(_repl, valeur)

    return {k: _rendu(v) for k, v in args.items()}


def parse_last_json(output: str) -> dict[str, object] | None:
    """Dernière ligne JSON-objet de la sortie du script (les infos du host créé)."""
    for line in reversed([ln.strip() for ln in output.splitlines() if ln.strip()]):
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def resultat_en_erreur(result: dict[str, object]) -> str | None:
    """Ligne `{"status":"error","stage":...,"message":...}` émise par le trap du
    script de création → libellé d'échec exploitable, ou None si succès."""
    if result.get("status") != "error":
        return None
    stage = str(result.get("stage") or "?")
    message = str(result.get("message") or "")
    return f"{stage} — {message}" if message else stage


def build_test_vm_args(params: dict[str, str], identifier_arg: str, vmid: str) -> dict[str, str]:
    """Args d'exécution : le paramétrage figé du type + l'identifiant fourni."""
    args = dict(params)
    args[identifier_arg] = vmid
    return args


def build_test_host_views(
    detailed: list[tuple[str, str]], hosts: list[HostConfig]
) -> list[dict[str, str]]:
    """Vue API des machines de test : `(host_name, alias)` + infos du `HostConfig`.

    `detailed` est déjà trié par numéro d'alias. Une association orpheline (host retiré
    de la config) est ignorée. L'IP et l'utilisateur SSH sont dérivés de `address`
    (`<user>@<ip>`) ; `user` vide si l'adresse n'a pas de partie `<user>@`.
    """
    by_name = {h.name: h for h in hosts}
    views: list[dict[str, str]] = []
    for host_name, alias in detailed:
        host = by_name.get(host_name)
        if host is None:
            continue
        user, sep, ip_part = host.address.partition("@")
        ip = ip_part if sep else user
        views.append(
            {
                "alias": alias,
                "name": host_name,
                "ip": ip if host.address else "",
                "user": user if (sep and host.address) else "",
                "vmid": host.vmid,
            }
        )
    return views


def replace_host_ip(old_address: str, new_ip: str) -> str:
    """Remplace l'IP d'une adresse SSH en préservant la partie `<user>@`.

    `debian@1.2.3.4` → `debian@<new_ip>` ; `1.2.3.4` → `<new_ip>` ; `''` → `<new_ip>`.
    """
    user, sep, _ = old_address.partition("@")
    return f"{user}@{new_ip}" if sep else new_ip


def build_testhost_ssh_command(
    host_name: str, allowed_names: Iterable[str], hosts: list[HostConfig]
) -> str | None:
    """Commande `ssh root@<ip>` à exécuter dans le container pour joindre une machine
    de test, ou ``None`` si l'accès n'est pas autorisé.

    Refusé si `host_name` n'est pas dans `allowed_names` (les test-hosts du workspace
    courant), si le host n'existe pas/plus, ou s'il n'est pas un host SSH `usage=tests`.
    L'IP est résolue côté serveur depuis le `HostConfig` — jamais fournie par le client.
    """
    if host_name not in set(allowed_names):
        return None
    host = next((h for h in hosts if h.name == host_name), None)
    if host is None or host.type != "ssh" or host.usage != "tests" or not host.address:
        return None
    ip = host.address.split("@", 1)[-1]
    dest = shlex.quote(f"root@{ip}")
    # VM de test éphémère (DHCP, recréée) → la clé d'hôte change légitimement ; pas de
    # known_hosts persistant côté container (évite "host key changed" au rebond).
    # Le terminal ouvre une session tmux persistante sur la VM (réattachable après
    # déconnexion) ; la commande distante est quotée pour le shell du container.
    return (
        "exec ssh -t -t -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-o ConnectTimeout=15 {dest} {shlex.quote(remote_tmux_command('main'))}"
    )


def map_result_to_host(result: dict[str, object], vmid: str, proxmox_node: str) -> HostConfig:
    """Convertit le JSON émis par le script de création en HostConfig `usage=tests`."""
    name = str(result.get("name") or "")
    address = str(result.get("address") or "")
    ssh_user = str(result.get("ssh_user") or "debian")
    resolved_vmid = str(result.get("vmid") or vmid or "")
    resolved_node = str(result.get("proxmox_node") or proxmox_node or "")

    if result.get("type") == "docker-tls":
        return HostConfig(
            name=name,
            type="docker-tls",
            docker_host=str(result.get("docker_host") or f"tcp://{address}:2376"),
            address="",
            vmid=resolved_vmid,
            proxmox_node=resolved_node,
            usage="tests",
        )
    return HostConfig(
        name=name,
        type="ssh",
        address=f"{ssh_user}@{address}",
        vmid=resolved_vmid,
        proxmox_node=resolved_node,
        usage="tests",
    )


def host_cert_ready(hosts: Iterable[HostConfig], host_name: str) -> bool:
    """True si `host_name` a un `host_cert_slug` posé (SSH portail actif → compose déployable)."""
    host = next((h for h in hosts if h.name == host_name), None)
    return bool(host and host.host_cert_slug)
