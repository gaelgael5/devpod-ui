# backend/tests/test_provisioning_existing.py
"""Driver « existing » (ticket 5) : enrôler une machine déjà là, et prouver que
le contrat ne fuit pas — un driver qui ne crée rien rend le même objet."""

from __future__ import annotations

import pytest

from portal.provisioning.contract import MachineDescriptor, MachineSpec
from portal.provisioning.driver import DriverError, driver_for
from portal.provisioning.existing import ExistingMachineDriver
from portal.provisioning.registry import register_builtin_drivers


def _spec(**provider_over: object) -> MachineSpec:
    provider: dict[str, object] = {
        "type": "existing",
        "address": "192.168.10.42",
        "key_path": "/data/keys/hosts/nuc-01_ed25519",
    }
    provider.update(provider_over)
    return MachineSpec.model_validate(
        {
            "name": "nuc-01",
            "cpu": 4,
            "memory_mb": 8192,
            "disk_gb": 40,
            "user": "debian",
            "ssh_authorized_keys": ["ssh-ed25519 AAAA test@host"],
            "network": {"mode": "dhcp"},
            "provider": provider,
        }
    )


class _ProbeSpy:
    def __init__(self, fail_with: str | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._fail_with = fail_with

    async def __call__(self, *, address: str, user: str, port: int, key_path: str) -> None:
        self.calls.append({"address": address, "user": user, "port": port, "key_path": key_path})
        if self._fail_with:
            raise DriverError(self._fail_with)


async def test_provision_valide_ssh_et_rend_le_descripteur() -> None:
    probe = _ProbeSpy()
    driver = ExistingMachineDriver(probe=probe)
    d = await driver.provision(_spec())
    assert isinstance(d, MachineDescriptor)
    assert d.address == "192.168.10.42"
    assert d.ssh_user == "debian"
    assert d.ssh_port == 22
    assert d.key_path == "/data/keys/hosts/nuc-01_ed25519"
    assert d.provider == "existing"
    assert probe.calls == [
        {
            "address": "192.168.10.42",
            "user": "debian",
            "port": 22,
            "key_path": "/data/keys/hosts/nuc-01_ed25519",
        }
    ]


async def test_provision_ne_cree_rien_provider_ref_vide() -> None:
    """Le test du contrat : rien n'a été créé, donc rien à référencer — et le
    descripteur reste valide avec un provider_ref vide et une provenance
    inconnue."""
    d = await ExistingMachineDriver(probe=_ProbeSpy()).provision(_spec())
    assert d.provider_ref == {}
    assert d.hypervisor == ""


async def test_provision_port_ssh_custom() -> None:
    d = await ExistingMachineDriver(probe=_ProbeSpy()).provision(_spec(ssh_port=2222))
    assert d.ssh_port == 2222


async def test_provision_sans_adresse_est_une_erreur() -> None:
    with pytest.raises(DriverError) as exc:
        await ExistingMachineDriver(probe=_ProbeSpy()).provision(_spec(address=None))
    assert "address" in str(exc.value)


async def test_provision_ssh_injoignable_est_une_erreur() -> None:
    probe = _ProbeSpy(fail_with="connexion refusée sur 192.168.10.42:22")
    with pytest.raises(DriverError) as exc:
        await ExistingMachineDriver(probe=probe).provision(_spec())
    assert "192.168.10.42" in str(exc.value)


async def test_destroy_ne_detruit_rien() -> None:
    """Le portail ne possède pas une machine enrôlée : destroy est un no-op qui
    accepte n'importe quel provider_ref sans le lire."""
    await ExistingMachineDriver(probe=_ProbeSpy()).destroy({"n_importe": "quoi"})
    await ExistingMachineDriver(probe=_ProbeSpy()).destroy({})


def test_registre_builtin_expose_existing() -> None:
    register_builtin_drivers()
    assert isinstance(driver_for("existing"), ExistingMachineDriver)
