# backend/tests/test_provisioning_proxmox.py
"""Driver Proxmox derrière le contrat (ticket 9) : mapping spec→module,
descripteur, échecs après création, destroy auto-portant, migration des hosts."""

from __future__ import annotations

from typing import Any

import pytest

from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    HostConfig,
    OidcConfig,
    ServerConfig,
)
from portal.provisioning.contract import MachineSpec
from portal.provisioning.errors import DriverError, EchecApresCreation
from portal.provisioning.migration_hosts import migrer_hosts_vers_provider_ref
from portal.provisioning.proxmox import ProxmoxTofuDriver


def _spec(**provider_over: object) -> MachineSpec:
    provider: dict[str, object] = {
        "type": "proxmox",
        "node": "pve",
        "template_vmid": 9000,
        "key_path": "/data/keys/hosts/ded-104_ed25519",
    }
    provider.update(provider_over)
    return MachineSpec.model_validate(
        {
            "name": "ded-104",
            "cpu": 4,
            "memory_mb": 8192,
            "disk_gb": 40,
            "user": "debian",
            "ssh_authorized_keys": ["ssh-ed25519 AAAA portal"],
            "network": {"mode": "dhcp"},
            "provider": provider,
        }
    )


class _FakeStack:
    def __init__(self, outputs: dict[str, Any] | None = None) -> None:
        self.outputs = (
            outputs
            if outputs is not None
            else {
                "vmid": 104,
                "node": "pve",
                "ipv4": "192.168.10.150",
            }
        )
        self.provisions: list[dict[str, Any]] = []
        self.destroys: list[dict[str, Any]] = []

    async def provision(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.provisions.append(variables)
        return self.outputs

    async def destroy(self, variables: dict[str, Any]) -> None:
        self.destroys.append(variables)


async def _probe_ok(**kwargs: Any) -> None:
    return None


async def _probe_ko(**kwargs: Any) -> None:
    raise DriverError("connexion refusée")


def _driver(stack: _FakeStack, probe: Any = _probe_ok) -> ProxmoxTofuDriver:
    return ProxmoxTofuDriver(
        module_dir=None,  # type: ignore[arg-type] — jamais lu : stack_factory injectée
        pg_conn_str="postgres://x/y",
        state_passphrase="passphrase-de-test-0123",
        endpoint="https://pve:8006",
        api_token="user@pam!portal=xxx",
        stack_factory=lambda **kw: stack,  # type: ignore[misc,return-value]
        ssh_probe=probe,
    )


async def test_provision_mappe_la_spec_et_rend_le_descripteur() -> None:
    stack = _FakeStack()
    d = await _driver(stack).provision(_spec())

    variables = stack.provisions[0]
    assert variables["name"] == "ded-104"
    assert variables["cpu"] == 4
    assert variables["memory_mb"] == 8192
    assert variables["disk_gb"] == 40
    assert variables["network_mode"] == "dhcp"
    assert variables["template_vmid"] == 9000
    assert "vmid" not in variables  # 0 = attribué par Proxmox

    assert d.address == "192.168.10.150"
    assert d.provider == "proxmox"
    assert d.provider_ref["vmid"] == "104"
    assert d.provider_ref["node"] == "pve"
    assert d.provider_ref["variables"] == variables
    assert d.hypervisor == "pve"
    assert d.key_path == "/data/keys/hosts/ded-104_ed25519"


async def test_provider_opaque_alimente_le_module() -> None:
    stack = _FakeStack()
    await _driver(stack).provision(
        _spec(vmid=222, storage="local-lvm", bridge="vmbr1", cpu_type="host")
    )
    variables = stack.provisions[0]
    assert variables["vmid"] == 222
    assert variables["storage"] == "local-lvm"
    assert variables["bridge"] == "vmbr1"
    assert variables["cpu_type"] == "host"


async def test_sans_node_ou_template_erreur_avant_tout() -> None:
    stack = _FakeStack()
    with pytest.raises(DriverError):
        await _driver(stack).provision(_spec(node=None))
    assert stack.provisions == []


async def test_machine_sans_adresse_est_un_echec_apres_creation() -> None:
    """L'apply a réussi : la VM existe. Sans adresse (agent absent), l'échec
    porte le ref — reprendre ou détruire, jamais une orpheline."""
    stack = _FakeStack(outputs={"vmid": 104, "node": "pve", "ipv4": ""})
    with pytest.raises(EchecApresCreation) as exc:
        await _driver(stack).provision(_spec())
    assert exc.value.provider_ref["vmid"] == "104"
    assert exc.value.provider == "proxmox"


async def test_ssh_indisponible_est_un_echec_apres_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("portal.provisioning.proxmox._SSH_WAIT_S", 0.05)
    monkeypatch.setattr("portal.provisioning.proxmox._SSH_RETRY_S", 0.01)
    stack = _FakeStack()
    with pytest.raises(EchecApresCreation) as exc:
        await _driver(stack, probe=_probe_ko).provision(_spec())
    assert exc.value.provider_ref["vmid"] == "104"


async def test_destroy_rejoue_les_variables_du_ref() -> None:
    stack = _FakeStack()
    ref = {
        "stack": "ded-104",
        "vmid": "104",
        "node": "pve",
        "variables": {"name": "ded-104", "template_vmid": 9000},
    }
    await _driver(stack).destroy(ref)
    assert stack.destroys == [{"name": "ded-104", "template_vmid": 9000}]


async def test_destroy_sans_ref_exploitable_est_une_erreur() -> None:
    with pytest.raises(DriverError) as exc:
        await _driver(_FakeStack()).destroy({"vmid": "104"})
    assert "import" in str(exc.value)


# ─── Migration des hosts existants (procédure du ticket 4, exécutée ici) ─────


def _cfg(hosts: list[HostConfig]) -> GlobalConfig:
    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=hosts,
    )


def test_migration_backfill_proxmox_et_existing() -> None:
    cfg = _cfg(
        [
            HostConfig(name="h-pve", type="ssh", vmid="104", proxmox_node="pve"),
            HostConfig(name="h-nuc", type="ssh"),
        ]
    )
    assert migrer_hosts_vers_provider_ref(cfg) == 2
    pve, nuc = cfg.hosts
    assert pve.provider == "proxmox"
    assert pve.provider_ref == {"vmid": "104", "node": "pve"}
    assert nuc.provider == "existing"
    assert nuc.provider_ref == {}


def test_migration_idempotente_et_ne_touche_pas_les_drivers() -> None:
    cfg = _cfg(
        [
            HostConfig(
                name="h-tofu",
                type="ssh",
                provider="proxmox",
                provider_ref={"stack": "h-tofu", "vmid": "150"},
            ),
        ]
    )
    assert migrer_hosts_vers_provider_ref(cfg) == 0
    assert cfg.hosts[0].provider_ref == {"stack": "h-tofu", "vmid": "150"}
