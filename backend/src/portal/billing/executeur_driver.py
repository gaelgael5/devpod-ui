"""Chemin « driver IaC » de l'exécuteur de provisionnement (ticket 9).

Activé par `HypervisorType.provisioning_driver` (vide = chemin script,
inchangé — le rollback est ce seul champ). Séquence :

1. clé SSH du portail générée (la privée sous `/data/ssh_keys/proxmox/`,
   la publique dans la spec) ;
2. `driver.provision(spec)` — création + attente SSH, contrat du ticket 4 ;
3. `configure-node.sh` depuis le portail sur le triplet du descripteur
   (paquets, docker, swap, tailnet si configuré) — la configuration reste
   hors du driver, règle du cadrage ;
4. `HostConfig` composé : `provider`/`provider_ref` du descripteur, et les
   colonnes historiques `vmid`/`proxmox_node` encore remplies depuis le ref
   opaque **par le driver proxmox lui-même via le descripteur** — jusqu'à
   l'étape 3 de la migration, les consommateurs legacy en ont besoin.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path
from typing import Any

import structlog

from ..config.models import HostConfig, Hypervisor, MachineProfile
from ..devpod.vm_init import generate_ed25519_keypair
from ..provisioning.contract import MachineDescriptor, MachineSpec, NetworkSpec
from ..provisioning.driver import driver_for
from ..routes.proxmox import _key_dir, _write_key_atomic

_log = structlog.get_logger(__name__)

_CONFIGURE_TIMEOUT_S = 1200.0


class ConfigurationEchouee(RuntimeError):
    """La machine existe et répond en SSH, mais A.10+ a échoué : c'est un
    échec APRÈS création — l'appelant a le descripteur pour agir."""

    def __init__(self, message: str, descriptor: MachineDescriptor) -> None:
        super().__init__(message)
        self.descriptor = descriptor


def composer_spec(
    *,
    nom: str,
    profil: MachineProfile,
    node: Hypervisor,
    driver_name: str,
    pubkey: str,
    key_path: str,
) -> MachineSpec:
    """La MachineSpec depuis le profil machine (cadrage des trois étages).

    Les params du profil, pour le chemin driver, portent le vocabulaire de la
    spec : `CPU`, `MEMORY_MB`, `DISK_GB` (absolu — le delta `DISK_EXTRA` du
    chemin script n'a pas d'équivalent fiable ici, refusé explicitement), et
    les clés provider (`TEMPLATE_VMID`, `STORAGE`, `BRIDGE`, `CPU_TYPE`).
    """
    params = profil.params
    if "DISK_GB" not in params and "DISK_EXTRA" in params:
        raise ValueError(
            f"profil {profil.slug!r} : le chemin driver exige DISK_GB (taille "
            "absolue) — DISK_EXTRA (delta) est un artefact du chemin script"
        )
    provider: dict[str, Any] = {
        "type": driver_name,
        "node": node.pve_node,
        "hypervisor": node.name,
        "key_path": key_path,
    }
    for cle_param, cle_provider in (
        ("TEMPLATE_VMID", "template_vmid"),
        ("STORAGE", "storage"),
        ("BRIDGE", "bridge"),
        ("CPU_TYPE", "cpu_type"),
        ("VMID", "vmid"),
    ):
        valeur = params.get(cle_param, "")
        if valeur and valeur != "auto":
            provider[cle_provider] = valeur
    return MachineSpec(
        name=nom,
        cpu=int(params.get("CPU") or params.get("CORES") or 4),
        memory_mb=int(params.get("MEMORY_MB") or params.get("MEMORY") or 8192),
        disk_gb=int(params.get("DISK_GB") or 40),
        user=params.get("CI_USER") or "debian",
        ssh_authorized_keys=[pubkey],
        network=NetworkSpec(mode="dhcp"),
        provider=provider,
    )


async def monter_par_driver(
    *,
    driver_name: str,
    nom: str,
    node: Hypervisor,
    profil: MachineProfile,
    portal_url: str,
    portal_token: str,
    tailnet_authkey: str = "",
) -> HostConfig:
    """Création par le contrat, configuration par configure-node.sh."""
    prive, publique = await generate_ed25519_keypair()
    key_path = _key_dir() / f"{nom}_ed25519"
    _write_key_atomic(key_path, prive.encode())

    spec = composer_spec(
        nom=nom,
        profil=profil,
        node=node,
        driver_name=driver_name,
        pubkey=publique.strip(),
        key_path=str(key_path),
    )
    descriptor = await driver_for(driver_name).provision(spec)

    adresse = await _configurer(
        descriptor,
        nom=nom,
        portal_url=portal_url,
        portal_token=portal_token,
        tailnet_authkey=tailnet_authkey,
    )

    return HostConfig(
        name=nom,
        type="ssh",
        address=f"{descriptor.ssh_user}@{adresse}",
        vmid=str(descriptor.provider_ref.get("vmid", "")),
        proxmox_node=str(descriptor.provider_ref.get("node", "")),
        provider=descriptor.provider,
        provider_ref=descriptor.provider_ref,
        usage="workspaces",
        profile_slug=profil.slug,
        hypervisor=descriptor.hypervisor,
    )


async def _configurer(
    descriptor: MachineDescriptor,
    *,
    nom: str,
    portal_url: str,
    portal_token: str,
    tailnet_authkey: str,
) -> str:
    """`configure-node.sh` sur le triplet du descripteur. Rend l'adresse
    finale : celle du tailnet si la machine l'a rejoint, sinon celle du
    descripteur."""
    try:
        script = _script_configure()
    except FileNotFoundError as exc:
        raise ConfigurationEchouee(str(exc), descriptor) from exc
    argv = [
        "bash",
        str(script),
        "--address",
        descriptor.address,
        "--user",
        descriptor.ssh_user,
        "--key",
        descriptor.key_path,
        "--node-name",
        nom,
    ]
    if portal_url and portal_token:
        argv += ["--portal-url", portal_url]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),  # noqa: S108 — ssh known_hosts
        # Les secrets en environnement, jamais en argv (ps auxww).
        "PORTAL_TOKEN": portal_token,
        "TAILNET_AUTHKEY": tailnet_authkey,
    }
    proc = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CONFIGURE_TIMEOUT_S)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        await proc.wait()
        raise ConfigurationEchouee(
            f"configure-node.sh ({nom}) : délai dépassé ({_CONFIGURE_TIMEOUT_S:.0f}s)",
            descriptor,
        ) from None
    sortie = stdout.decode(errors="replace")
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[-500:]
        raise ConfigurationEchouee(
            f"configure-node.sh ({nom}) : rc={proc.returncode} — {detail}", descriptor
        )
    # Contrat de l'étape A.10e : l'adresse de tailnet prime quand elle existe.
    for ligne in sortie.splitlines():
        if ligne.startswith("TAILNET_IP="):
            return ligne.split("=", 1)[1].strip()
    return descriptor.address


def _script_configure() -> Path:
    for candidat in (
        Path("/app/scripts/configure-node.sh"),
        Path(__file__).parents[4] / "scripts" / "configure-node.sh",
    ):
        if candidat.is_file():
            return candidat
    raise FileNotFoundError("configure-node.sh introuvable (ni /app/scripts, ni scripts/)")
