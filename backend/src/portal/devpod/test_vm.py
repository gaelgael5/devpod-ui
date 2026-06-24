"""Logique de création d'une VM de test (host `usage=tests`).

Parties pures (mapping résultat → HostConfig, construction des args) ; l'exécution
SSH et la persistance vivent dans la route `/me`.
"""
from __future__ import annotations

import json

from ..config.models import HostConfig


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


def build_test_vm_args(
    params: dict[str, str], identifier_arg: str, vmid: str
) -> dict[str, str]:
    """Args d'exécution : le paramétrage figé du type + l'identifiant fourni."""
    args = dict(params)
    args[identifier_arg] = vmid
    return args


def map_result_to_host(
    result: dict[str, object], vmid: str, proxmox_node: str
) -> HostConfig:
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
