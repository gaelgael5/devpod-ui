# backend/tests/test_provisioning_azure.py
"""Driver Azure (ticket 10) : résolution demande→SKU, tailnet obligatoire,
destroy en cascade + désenrôlement."""

from __future__ import annotations

from typing import Any

import pytest

from portal.provisioning.azure import AzureTofuDriver, resoudre_sku
from portal.provisioning.contract import MachineSpec
from portal.provisioning.driver import DriverError
from portal.provisioning.errors import EchecApresCreation


def _spec(**provider_over: object) -> MachineSpec:
    provider: dict[str, object] = {
        "type": "azure",
        "region": "francecentral",
        "key_path": "/data/ssh_keys/proxmox/az-01_ed25519",
    }
    provider.update(provider_over)
    return MachineSpec.model_validate(
        {
            "name": "az-01",
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
    def __init__(self) -> None:
        self.provisions: list[dict[str, Any]] = []
        self.destroys: list[dict[str, Any]] = []

    async def provision(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.provisions.append(variables)
        return {
            "resource_group": "rg-az-01",
            "private_ip": "10.42.0.4",
            "vm_id": "/subscriptions/s/resourceGroups/rg-az-01/…/az-01",
        }

    async def destroy(self, variables: dict[str, Any]) -> None:
        self.destroys.append(variables)


class _FakeTailnet:
    def __init__(self, ip: str | None = "100.101.102.103") -> None:
        self.ip = ip
        self.cles: list[str] = []
        self.desenroles: list[str] = []

    async def creer_cle_enrolement(self, *, hostname: str) -> str:
        self.cles.append(hostname)
        return "tskey-auth-usage-unique"

    async def ip_du_noeud(self, hostname: str) -> str | None:
        return self.ip

    async def desenroler(self, hostname: str) -> bool:
        self.desenroles.append(hostname)
        return True


def _driver(stack: _FakeStack, tailnet: _FakeTailnet) -> AzureTofuDriver:
    return AzureTofuDriver(
        module_dir=None,  # type: ignore[arg-type] — stack_factory injectée
        pg_conn_str="postgres://x/y",
        state_passphrase="passphrase-de-test-0123",
        arm_env={"ARM_CLIENT_SECRET": "s"},
        tailnet=tailnet,  # type: ignore[arg-type]
        stack_factory=lambda **kw: stack,  # type: ignore[misc,return-value]
    )


# ─── Résolution demande → SKU (le tranchage du spike, en fonction pure) ──────


def test_sku_plus_petit_suffisant() -> None:
    sku, resolved = resoudre_sku(4, 8192)
    assert sku == "Standard_D4ads_v5"
    assert resolved.cpu == 4
    assert resolved.memory_mb == 16384  # l'arrondi est VISIBLE, pas silencieux


def test_sku_la_memoire_peut_forcer_le_cpu() -> None:
    sku, resolved = resoudre_sku(2, 24576)
    assert sku == "Standard_D8ads_v5"
    assert resolved.cpu == 8


def test_sku_famille_burstable() -> None:
    sku, _ = resoudre_sku(2, 4096, famille="Bs_v2")
    assert sku == "Standard_B2s_v2"


def test_sku_demande_impossible() -> None:
    with pytest.raises(DriverError):
        resoudre_sku(128, 8192)


def test_sku_famille_inconnue() -> None:
    with pytest.raises(DriverError):
        resoudre_sku(4, 8192, famille="Exotique_v9")


# ─── Provision ────────────────────────────────────────────────────────────────


async def test_provision_resout_le_sku_et_rend_l_adresse_tailnet() -> None:
    stack, tailnet = _FakeStack(), _FakeTailnet()
    d = await _driver(stack, tailnet).provision(_spec())

    variables = stack.provisions[0]
    assert variables["instance_size"] == "Standard_D4ads_v5"
    assert variables["region"] == "francecentral"
    assert variables["tailnet_authkey"] == "tskey-auth-usage-unique"
    assert tailnet.cles == ["az-01"]

    # L'adresse est celle du TAILNET, jamais l'IP privée du vnet.
    assert d.address == "100.101.102.103"
    assert d.provider == "azure"
    assert d.provider_ref["resource_group"] == "rg-az-01"
    assert d.resolved is not None and d.resolved.instance_size == "Standard_D4ads_v5"


async def test_instance_size_explicite_court_circuite() -> None:
    stack = _FakeStack()
    d = await _driver(stack, _FakeTailnet()).provision(_spec(instance_size="Standard_D2as_v6"))
    assert stack.provisions[0]["instance_size"] == "Standard_D2as_v6"
    assert d.resolved is None  # allocation littérale : rien d'arrondi


async def test_le_ref_ne_porte_jamais_la_cle_tailnet() -> None:
    stack = _FakeStack()
    d = await _driver(stack, _FakeTailnet()).provision(_spec())
    assert "tailnet_authkey" not in d.provider_ref["variables"]


async def test_sans_region_erreur_avant_tout() -> None:
    stack, tailnet = _FakeStack(), _FakeTailnet()
    with pytest.raises(DriverError):
        await _driver(stack, tailnet).provision(_spec(region=None))
    assert stack.provisions == []
    assert tailnet.cles == []


async def test_machine_hors_tailnet_est_un_echec_apres_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("portal.provisioning.azure._TAILNET_WAIT_S", 0.05)
    monkeypatch.setattr("portal.provisioning.azure._TAILNET_RETRY_S", 0.01)
    stack = _FakeStack()
    with pytest.raises(EchecApresCreation) as exc:
        await _driver(stack, _FakeTailnet(ip=None)).provision(_spec())
    assert exc.value.provider_ref["resource_group"] == "rg-az-01"


# ─── Destroy ──────────────────────────────────────────────────────────────────


async def test_destroy_cascade_et_desenrole() -> None:
    stack, tailnet = _FakeStack(), _FakeTailnet()
    ref = {
        "stack": "az-01",
        "resource_group": "rg-az-01",
        "variables": {"name": "az-01", "region": "francecentral"},
    }
    await _driver(stack, tailnet).destroy(ref)
    assert stack.destroys[0]["name"] == "az-01"
    assert tailnet.desenroles == ["az-01"]


async def test_destroy_sans_ref_exploitable() -> None:
    with pytest.raises(DriverError):
        await _driver(_FakeStack(), _FakeTailnet()).destroy({"resource_group": "rg-x"})
