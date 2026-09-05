"""Driver Azure derrière le contrat — module OpenTofu (ticket 10).

La demande `cpu`/`memory_mb` est résolue vers le **plus petit SKU suffisant**
d'une famille déclarée (tranchage du spike, ticket 3) : fonction pure,
déterministe, testable hors ligne. `provider.instance_size` court-circuite.

Une VM Azure n'est joignable que par le tailnet (zéro IP publique, NSG fermé) :
le driver crée la clé d'enrôlement, le module la consomme en cloud-init au
premier boot, puis le driver attend l'adresse 100.64/10 du nœud. `destroy`
détruit le resource group (cascade) ET désenrôle le nœud du tailnet.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from .contract import MachineDescriptor, MachineSpec, ResolvedResources
from .errors import DriverError, EchecApresCreation
from .tailnet import TailnetService
from .tofu import TofuStack

_log = structlog.get_logger(__name__)

# Familles de SKU supportées : (motif de nom, vCPU disponibles, Mo par vCPU).
# Déclaratif et local — la résolution ne fait aucun appel réseau. Étendre ici
# quand une famille manque, plutôt que de deviner un nom de SKU.
_FAMILLES: dict[str, tuple[str, tuple[int, ...], int]] = {
    "Dads_v5": ("Standard_D{n}ads_v5", (2, 4, 8, 16, 32, 48, 64, 96), 4096),
    "Bs_v2": ("Standard_B{n}s_v2", (2, 4, 8, 16, 32), 4096),
}

_TAILNET_WAIT_S = 600.0
_TAILNET_RETRY_S = 10.0

StackFactory = Callable[..., TofuStack]


def resoudre_sku(
    cpu: int, memory_mb: int, famille: str = "Dads_v5"
) -> tuple[str, ResolvedResources]:
    """Plus petit SKU de la famille couvrant cpu ET mémoire. Rend aussi ce qui
    a été réellement alloué — l'utilisateur voit l'arrondi (`resolved`)."""
    if famille not in _FAMILLES:
        raise DriverError(f"famille de SKU inconnue : {famille!r} (connues : {sorted(_FAMILLES)})")
    motif, tailles, mo_par_vcpu = _FAMILLES[famille]
    for n in tailles:
        if n >= cpu and n * mo_par_vcpu >= memory_mb:
            return motif.format(n=n), ResolvedResources(
                cpu=n, memory_mb=n * mo_par_vcpu, instance_size=motif.format(n=n)
            )
    raise DriverError(
        f"aucun SKU {famille} ne couvre {cpu} vCPU / {memory_mb} Mo (max {tailles[-1]} vCPU)"
    )


class AzureTofuDriver:
    """`provider` attendu : `{"type": "azure", "region": ..., "instance_size"?,
    "sku_family"?, "resource_group"?, "image"?, "key_path"?}`."""

    def __init__(
        self,
        *,
        module_dir: Path,
        pg_conn_str: str,
        state_passphrase: str,
        arm_env: dict[str, str],
        tailnet: TailnetService,
        tofu_binary: str = "tofu",
        provider_mirror: Path | None = None,
        timeout_s: float = 1800.0,
        stack_factory: StackFactory | None = None,
    ) -> None:
        self._module_dir = module_dir
        self._pg_conn_str = pg_conn_str
        self._passphrase = state_passphrase
        self._arm_env = dict(arm_env)
        self._tailnet = tailnet
        self._tofu_binary = tofu_binary
        self._provider_mirror = provider_mirror
        self._timeout_s = timeout_s
        self._stack_factory = stack_factory

    # ─── Contrat ─────────────────────────────────────────────────────────────

    async def provision(self, spec: MachineSpec) -> MachineDescriptor:
        region = spec.provider.get("region")
        if not isinstance(region, str) or not region:
            raise DriverError("driver azure : provider.region est obligatoire")

        instance_size = str(spec.provider.get("instance_size") or "")
        resolved: ResolvedResources | None = None
        if not instance_size:
            famille = str(spec.provider.get("sku_family") or "Dads_v5")
            instance_size, resolved = resoudre_sku(spec.cpu, spec.memory_mb, famille)

        # La clé d'enrôlement (usage unique) est créée ICI : le module la
        # consomme en cloud-init — seul chemin vers une machine sans IP
        # publique. La spec ne porte jamais de secret.
        authkey = await self._tailnet.creer_cle_enrolement(hostname=spec.name)

        variables: dict[str, Any] = {
            "name": spec.name,
            "disk_gb": spec.disk_gb,
            "user": spec.user,
            "ssh_authorized_keys": spec.ssh_authorized_keys,
            "region": region,
            "instance_size": instance_size,
            "tailnet_authkey": authkey,
        }
        for optionnel in ("resource_group", "image", "subnet_cidr"):
            if spec.provider.get(optionnel):
                variables[optionnel] = spec.provider[optionnel]
        owner_tags = spec.provider.get("owner_tags")
        if isinstance(owner_tags, dict):
            variables["owner_tags"] = owner_tags

        stack = self._stack(spec.name)
        outputs = await stack.provision(variables)

        ref = {
            "stack": spec.name,
            "resource_group": str(outputs.get("resource_group") or ""),
            "vm_id": str(outputs.get("vm_id") or ""),
            "variables": {k: v for k, v in variables.items() if k != "tailnet_authkey"},
        }
        address = await self._attendre_tailnet(spec.name, ref)

        _log.info(
            "azure_machine_provisionnee",
            name=spec.name,
            resource_group=ref["resource_group"],
            instance_size=instance_size,
        )
        return MachineDescriptor(
            address=address,
            ssh_user=spec.user,
            ssh_port=22,
            key_path=str(spec.provider.get("key_path", "")),
            provider="azure",
            provider_ref=ref,
            hypervisor=str(spec.provider.get("hypervisor", "")),
            resolved=resolved,
        )

    async def destroy(self, provider_ref: dict[str, Any]) -> None:
        stack_name = str(provider_ref.get("stack") or "")
        variables = provider_ref.get("variables")
        if not stack_name or not isinstance(variables, dict):
            raise DriverError(
                "provider_ref inexploitable pour destroy (stack/variables absents) — "
                "machine à réadopter via la procédure d'import du socle IaC"
            )
        # La variable sensible est requise par le module ; sa valeur n'importe
        # plus à la destruction (la clé d'origine est morte depuis longtemps).
        stack = self._stack(stack_name)
        await stack.destroy({**variables, "tailnet_authkey": "destroy"})
        # Un nœud détruit doit disparaître du tailnet, sinon les fantômes
        # s'accumulent et un nom réutilisé prend un suffixe qui casse tout.
        await self._tailnet.desenroler(stack_name)
        _log.info("azure_machine_detruite", stack=stack_name)

    # ─── Mécanique ───────────────────────────────────────────────────────────

    def _stack(self, stack_name: str) -> TofuStack:
        if self._stack_factory is not None:
            return self._stack_factory(stack=stack_name)
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
            secret_env=self._arm_env,
            timeout_s=self._timeout_s,
        )

    async def _attendre_tailnet(self, hostname: str, ref: dict[str, Any]) -> str:
        """La machine existe ; sans adhésion tailnet elle est injoignable —
        échec APRÈS création, jamais un repli sur l'IP privée (qui ne marche
        pas depuis le portail, règle du ticket 7)."""
        echeance = asyncio.get_event_loop().time() + _TAILNET_WAIT_S
        while True:
            ip = await self._tailnet.ip_du_noeud(hostname)
            if ip:
                return ip
            if asyncio.get_event_loop().time() >= echeance:
                break
            await asyncio.sleep(_TAILNET_RETRY_S)
        raise EchecApresCreation(
            f"machine {hostname} créée mais absente du tailnet après "
            f"{_TAILNET_WAIT_S:.0f}s — cloud-init/tailscale en échec ? "
            "Reprendre ou détruire.",
            provider_ref=ref,
            provider="azure",
        )
