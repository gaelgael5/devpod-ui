# backend/tests/test_provisioning_contract.py
"""Contrat de driver de provisionnement (ticket 4) : MachineSpec,
MachineDescriptor, provider_ref opaque, et l'équivalence des deux protocoles
de driver (module Python vs exécutable JSON stdin/stdout)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from portal.provisioning.contract import (
    MachineDescriptor,
    MachineSpec,
    NetworkSpec,
)
from portal.provisioning.driver import (
    DriverError,
    ExecutableDriver,
    driver_for,
    register_driver,
)


def _spec(**over: object) -> MachineSpec:
    base: dict[str, object] = {
        "name": "pve2-docker",
        "cpu": 4,
        "memory_mb": 8192,
        "disk_gb": 40,
        "user": "debian",
        "ssh_authorized_keys": ["ssh-ed25519 AAAA test@host"],
        "network": {"mode": "dhcp"},
        "provider": {"type": "proxmox", "template_vmid": "9000"},
    }
    base.update(over)
    return MachineSpec.model_validate(base)


# ─── MachineSpec ──────────────────────────────────────────────────────────────


def test_spec_nominale_proxmox() -> None:
    spec = _spec()
    assert spec.provider["type"] == "proxmox"
    assert spec.network.mode == "dhcp"


def test_spec_nominale_azure() -> None:
    spec = _spec(
        provider={
            "type": "azure",
            "region": "francecentral",
            "instance_size": "Standard_D4ads_v5",
        }
    )
    assert spec.provider["region"] == "francecentral"


def test_spec_provider_type_obligatoire() -> None:
    with pytest.raises(ValidationError):
        _spec(provider={"region": "francecentral"})


def test_spec_refuse_vmid_hors_provider() -> None:
    with pytest.raises(ValidationError):
        _spec(vmid="104")


def test_spec_nom_invalide_rejete() -> None:
    with pytest.raises(ValidationError):
        _spec(name="Bad_Name!")


def test_spec_static_exige_adresse() -> None:
    with pytest.raises(ValidationError):
        NetworkSpec.model_validate({"mode": "static"})
    net = NetworkSpec.model_validate(
        {"mode": "static", "address": "192.168.1.50/24", "gateway": "192.168.1.1"}
    )
    assert net.address == "192.168.1.50/24"


def test_spec_ressources_positives() -> None:
    with pytest.raises(ValidationError):
        _spec(cpu=0)
    with pytest.raises(ValidationError):
        _spec(memory_mb=-1)


# ─── MachineDescriptor ────────────────────────────────────────────────────────


def _descriptor(**over: object) -> MachineDescriptor:
    base: dict[str, object] = {
        "status": "ok",
        "address": "192.168.1.50",
        "ssh_user": "debian",
        "ssh_port": 22,
        "key_path": "/data/keys/hosts/pve2-docker_ed25519",
        "provider": "proxmox",
        "provider_ref": {"vmid": "104", "node": "pve2"},
        "hypervisor": "pve2",
    }
    base.update(over)
    return MachineDescriptor.model_validate(base)


def test_descriptor_nominal() -> None:
    d = _descriptor()
    assert d.provider_ref["vmid"] == "104"
    assert d.hypervisor == "pve2"


def test_descriptor_provider_ref_opaque_round_trip() -> None:
    """Le portail stocke et repasse provider_ref tel quel : le round-trip JSON
    doit être byte-identique, y compris pour des clés inconnues."""
    ref = {"vmid": "104", "node": "pve2", "exotique": {"nested": [1, 2]}}
    d = _descriptor(provider_ref=ref)
    dumped = d.model_dump()["provider_ref"]
    assert dumped == ref


def test_descriptor_sans_secret() -> None:
    """Aucun champ de secret en valeur : le mot de passe console passe par un
    slug Harpocrate, la clé par un chemin."""
    with pytest.raises(ValidationError):
        _descriptor(ci_password="cleartext")
    d = _descriptor(ci_password_secret_slug="hosts/pve2-docker/ci")
    assert d.ci_password_secret_slug == "hosts/pve2-docker/ci"


def test_descriptor_hypervisor_vide_est_inconnu() -> None:
    d = _descriptor(hypervisor="")
    assert d.hypervisor == ""


def test_descriptor_resolved_optionnel() -> None:
    d = _descriptor(resolved={"cpu": 4, "memory_mb": 16384, "instance_size": "Standard_D4ads_v5"})
    assert d.resolved is not None
    assert d.resolved.instance_size == "Standard_D4ads_v5"


# ─── Registre de drivers ──────────────────────────────────────────────────────


def test_registre_driver_inconnu() -> None:
    with pytest.raises(DriverError):
        driver_for("hyperviseur-exotique-inconnu")


# ─── Protocole exécutable (JSON stdin/stdout) ────────────────────────────────


ECHO_DRIVER = """#!/usr/bin/env bash
# Driver de test : provisionne « en écho » — rend un descripteur dérivé de la
# spec reçue sur stdin, prouve que le protocole executable == interface Python.
set -euo pipefail
input=$(cat)
action=$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['action'])" "$input")
if [ "$action" = "provision" ]; then
    python3 - "$input" <<'PY'
import json, sys
req = json.loads(sys.argv[1])
spec = req["spec"]
print(json.dumps({
    "status": "ok",
    "address": "203.0.113.10",
    "ssh_user": spec["user"],
    "ssh_port": 22,
    "key_path": "/data/keys/hosts/%s_ed25519" % spec["name"],
    "provider": spec["provider"]["type"],
    "provider_ref": {"echo": spec["name"]},
    "hypervisor": "",
}))
PY
elif [ "$action" = "destroy" ]; then
    echo '{"status": "ok"}'
else
    echo "action inconnue: $action" >&2
    exit 2
fi
"""


@pytest.fixture
def echo_driver(tmp_path: Path) -> ExecutableDriver:
    exe = tmp_path / "echo-driver"
    exe.write_text(ECHO_DRIVER)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return ExecutableDriver(executable=exe)


async def test_executable_provision_rend_le_meme_objet(
    echo_driver: ExecutableDriver,
) -> None:
    """DoD : le protocole exécutable donne le même résultat que l'interface
    Python sur un cas de test."""
    spec = _spec()
    d = await echo_driver.provision(spec)
    assert isinstance(d, MachineDescriptor)
    assert d.ssh_user == "debian"
    assert d.provider_ref == {"echo": "pve2-docker"}


async def test_executable_destroy_passe_le_ref_tel_quel(
    echo_driver: ExecutableDriver, tmp_path: Path
) -> None:
    trace = tmp_path / "trace.json"
    exe = tmp_path / "trace-driver"
    exe.write_text(
        f'#!/usr/bin/env bash\nset -euo pipefail\ncat > {trace}\necho \'{{"status": "ok"}}\'\n'
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    driver = ExecutableDriver(executable=exe)
    ref = {"vmid": "104", "node": "pve2", "exotique": True}
    await driver.destroy(ref)
    recu = json.loads(trace.read_text())
    assert recu == {"action": "destroy", "provider_ref": ref}


async def test_executable_echec_leve_une_erreur_typee(tmp_path: Path) -> None:
    exe = tmp_path / "bad-driver"
    exe.write_text("#!/usr/bin/env bash\necho 'quota dépassé' >&2\nexit 3\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    driver = ExecutableDriver(executable=exe)
    with pytest.raises(DriverError) as exc:
        await driver.provision(_spec())
    assert "quota dépassé" in str(exc.value)


async def test_executable_sortie_non_json_est_une_erreur(tmp_path: Path) -> None:
    exe = tmp_path / "garbage-driver"
    exe.write_text("#!/usr/bin/env bash\necho 'pas du json'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    driver = ExecutableDriver(executable=exe)
    with pytest.raises(DriverError):
        await driver.provision(_spec())


def test_register_driver_et_resolution() -> None:
    class _Fake:
        async def provision(self, spec: MachineSpec) -> MachineDescriptor:
            raise NotImplementedError

        async def destroy(self, provider_ref: dict[str, object]) -> None:
            raise NotImplementedError

    register_driver("fake-test-provider", _Fake())
    assert driver_for("fake-test-provider") is not None
