"""Driver Proxmox derrière le contrat — module OpenTofu (ticket 9).

Le module (`deploy/tofu-modules/proxmox-vm`) refait A.1→A.7 du script en
déclaratif ; ce driver le pilote via `TofuStack` et s'arrête quand la machine
répond en SSH — la configuration (A.10+) reste à `configure-node.sh`, déroulée
par le portail comme recette du profil machine.

`provider_ref` rendu : `{"stack", "vmid", "node", "variables"}`. Les variables
du module y sont recopiées pour que `destroy` soit auto-portant (le module en a
besoin pour planifier) — elles ne contiennent aucun secret (les clés SSH sont
publiques). Le portail stocke ce bloc sans jamais le lire : c'est le contrat.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from .contract import MachineDescriptor, MachineSpec
from .errors import DriverError, EchecApresCreation
from .existing import SshProbe, _probe_ssh
from .tofu import TofuStack

_log = structlog.get_logger(__name__)

# Même horizon que le script : SSH opérationnel en ~20 s au premier boot,
# pire cas cloud-init sur host chargé ~90 s. Au-delà de 120 s c'est une panne.
_SSH_WAIT_S = 120.0
_SSH_RETRY_S = 5.0

StackFactory = Callable[..., TofuStack]


class ProxmoxTofuDriver:
    """`provider` attendu dans la spec : `{"type": "proxmox", "node": ...,
    "template_vmid": ..., "vmid"?, "storage"?, "bridge"?, "cpu_type"?,
    "key_path"?, "hypervisor"?}` — `key_path` est la clé privée côté portail
    qui répond aux `ssh_authorized_keys` injectées."""

    def __init__(
        self,
        *,
        module_dir: Path,
        pg_conn_str: str,
        state_passphrase: str,
        endpoint: str,
        api_token: str,
        tofu_binary: str = "tofu",
        provider_mirror: Path | None = None,
        timeout_s: float = 900.0,
        stack_factory: StackFactory | None = None,
        ssh_probe: SshProbe | None = None,
    ) -> None:
        self._module_dir = module_dir
        self._pg_conn_str = pg_conn_str
        self._passphrase = state_passphrase
        self._endpoint = endpoint
        self._api_token = api_token
        self._tofu_binary = tofu_binary
        self._provider_mirror = provider_mirror
        self._timeout_s = timeout_s
        self._stack_factory = stack_factory
        self._ssh_probe = ssh_probe

    # ─── Contrat ─────────────────────────────────────────────────────────────

    async def provision(self, spec: MachineSpec) -> MachineDescriptor:
        variables = self._variables(spec)
        stack = self._stack(spec.name)
        outputs = await stack.provision(variables)

        vmid = str(outputs.get("vmid") or "")
        node = str(outputs.get("node") or variables["node"])
        ref = {
            "stack": spec.name,
            "vmid": vmid,
            "node": node,
            "variables": variables,
        }
        address = str(outputs.get("ipv4") or "")
        if not address:
            # La machine EXISTE (l'apply a réussi) mais l'agent QEMU n'a pas
            # rendu d'adresse : sans elle, pas de configuration possible. Le
            # repli ping-sweep reste sur le chemin legacy (script).
            raise EchecApresCreation(
                f"machine {spec.name} (vmid {vmid}) créée mais sans adresse — "
                "agent QEMU absent du template ? Reprendre ou détruire.",
                provider_ref=ref,
                provider="proxmox",
            )

        key_path = str(spec.provider.get("key_path", ""))
        await self._attendre_ssh(address=address, user=spec.user, key_path=key_path, ref=ref)

        _log.info("proxmox_machine_provisionnee", name=spec.name, vmid=vmid, node=node)
        return MachineDescriptor(
            address=address,
            ssh_user=spec.user,
            ssh_port=22,
            key_path=key_path,
            provider="proxmox",
            provider_ref=ref,
            hypervisor=str(spec.provider.get("hypervisor", node)),
        )

    async def destroy(self, provider_ref: dict[str, Any]) -> None:
        stack_name = str(provider_ref.get("stack") or "")
        variables = provider_ref.get("variables")
        if not stack_name or not isinstance(variables, dict):
            raise DriverError(
                "provider_ref inexploitable pour destroy (stack/variables absents) — "
                "machine à réadopter via la procédure d'import du socle IaC"
            )
        stack = self._stack(stack_name)
        await stack.destroy(variables)
        _log.info("proxmox_machine_detruite", stack=stack_name)

    # ─── Mécanique ───────────────────────────────────────────────────────────

    def _variables(self, spec: MachineSpec) -> dict[str, Any]:
        provider = spec.provider
        for requis in ("node", "template_vmid"):
            if not provider.get(requis):
                raise DriverError(f"driver proxmox : provider.{requis} est obligatoire")
        variables: dict[str, Any] = {
            "name": spec.name,
            "cpu": spec.cpu,
            "memory_mb": spec.memory_mb,
            "disk_gb": spec.disk_gb,
            "user": spec.user,
            "ssh_authorized_keys": spec.ssh_authorized_keys,
            "network_mode": spec.network.mode,
            "network_address": spec.network.address or "",
            "network_gateway": spec.network.gateway or "",
            "network_dns": spec.network.dns or "",
            "node": provider["node"],
            "template_vmid": int(provider["template_vmid"]),
        }
        if provider.get("vmid"):
            variables["vmid"] = int(provider["vmid"])
        for optionnel in ("storage", "bridge", "cpu_type"):
            if provider.get(optionnel):
                variables[optionnel] = provider[optionnel]
        return variables

    def _stack(self, stack_name: str) -> TofuStack:
        if self._stack_factory is not None:
            return self._stack_factory(stack=stack_name)
        # Copie du module dans un répertoire de travail dédié : deux
        # provisionnements concurrents ne partagent ni lock d'init ni plan.
        workdir = Path(tempfile.mkdtemp(prefix=f"tofu-{stack_name}-"))
        for tf in self._module_dir.glob("*.tf"):
            shutil.copy(tf, workdir / tf.name)
        return TofuStack(
            workdir=workdir,
            stack=stack_name,
            pg_conn_str=self._pg_conn_str,
            state_passphrase=self._passphrase,
            binary=self._tofu_binary,
            provider_mirror=self._provider_mirror,
            secret_env={
                "PROXMOX_VE_ENDPOINT": self._endpoint,
                "PROXMOX_VE_API_TOKEN": self._api_token,
            },
            timeout_s=self._timeout_s,
        )

    async def _attendre_ssh(
        self, *, address: str, user: str, key_path: str, ref: dict[str, Any]
    ) -> None:
        """Le module rend la main dès que l'agent donne une IP ; le contrat du
        driver est « la machine répond en SSH ». Même logique que A.9 : le vrai
        SSH par clé, retenté — sshd ouvre le port avant que cloud-init n'écrive
        authorized_keys. Un timeout ici est un échec APRÈS création : la VM
        existe, le ref part avec l'erreur pour la reprendre ou la détruire."""
        probe = self._ssh_probe or _probe_ssh
        echeance = asyncio.get_event_loop().time() + _SSH_WAIT_S
        derniere: DriverError | None = None
        while True:
            try:
                await probe(address=address, user=user, port=22, key_path=key_path)
                return
            except DriverError as exc:
                derniere = exc
                if asyncio.get_event_loop().time() >= echeance:
                    break
                await asyncio.sleep(_SSH_RETRY_S)
        raise EchecApresCreation(
            f"machine {address} créée mais SSH indisponible après {_SSH_WAIT_S:.0f}s — {derniere}",
            provider_ref=ref,
            provider="proxmox",
        )
