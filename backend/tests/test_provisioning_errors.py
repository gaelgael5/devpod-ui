# backend/tests/test_provisioning_errors.py
"""Taxonomie des échecs (ticket 6) et sa traduction par ExecutableDriver."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from portal.provisioning.contract import MachineSpec
from portal.provisioning.driver import DriverError, ExecutableDriver
from portal.provisioning.errors import (
    EchecApresCreation,
    EchecAvantCreation,
    Indetermine,
    provider_ref_of,
    run_state_for,
)


def _spec() -> MachineSpec:
    return MachineSpec.model_validate(
        {
            "name": "n1",
            "cpu": 2,
            "memory_mb": 2048,
            "disk_gb": 20,
            "user": "debian",
            "ssh_authorized_keys": ["ssh-ed25519 AAAA t@h"],
            "network": {"mode": "dhcp"},
            "provider": {"type": "test"},
        }
    )


def _driver(tmp_path: Path, script: str, timeout_s: float = 30.0) -> ExecutableDriver:
    exe = tmp_path / "driver"
    exe.write_text(script)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return ExecutableDriver(executable=exe, timeout_s=timeout_s)


# ─── Mapping état ─────────────────────────────────────────────────────────────


def test_run_state_pour_chaque_categorie() -> None:
    assert run_state_for(EchecAvantCreation("x")) == "echec_avant_creation"
    assert (
        run_state_for(EchecApresCreation("x", provider_ref={"vmid": "1"}))
        == "echec_apres_creation"
    )
    assert run_state_for(Indetermine("x")) == "indetermine"


def test_exception_hors_taxonomie_est_indeterminee() -> None:
    """Un bug (KeyError…) ne dit pas ce que l'exécution a laissé : prudence."""
    assert run_state_for(KeyError("boom")) == "indetermine"
    assert run_state_for(DriverError("generique")) == "indetermine"


def test_apres_creation_exige_un_ref() -> None:
    with pytest.raises(ValueError):
        EchecApresCreation("x", provider_ref={})


def test_provider_ref_of() -> None:
    exc = EchecApresCreation("x", provider_ref={"vmid": "104"})
    assert provider_ref_of(exc) == {"vmid": "104"}
    assert provider_ref_of(EchecAvantCreation("x")) is None


# ─── Classification par ExecutableDriver ─────────────────────────────────────


async def test_echec_avec_provider_ref_est_apres_creation(tmp_path: Path) -> None:
    """Le driver a émis un JSON d'erreur portant provider_ref (la machine
    existe) : l'échec doit le transporter, c'est ce qui évite l'orpheline."""
    script = (
        "#!/usr/bin/env bash\n"
        "echo 'clonage ok, config en échec' >&2\n"
        'echo \'{"status":"error","stage":"A.10","provider_ref":{"vmid":"150","node":"pve"}}\'\n'
        "exit 1\n"
    )
    with pytest.raises(EchecApresCreation) as exc:
        await _driver(tmp_path, script).provision(_spec())
    assert exc.value.provider_ref == {"vmid": "150", "node": "pve"}
    assert "A.10" in str(exc.value)


async def test_echec_sans_provider_ref_est_avant_creation(tmp_path: Path) -> None:
    """Contrat du driver : provider_ref dès que la machine existe. Son absence
    dans le JSON d'erreur signifie qu'il n'y a rien derrière."""
    script = (
        "#!/usr/bin/env bash\n"
        "echo 'VMID occupé' >&2\n"
        'echo \'{"status":"error","stage":"A.1","message":"VMID occupé"}\'\n'
        "exit 1\n"
    )
    with pytest.raises(EchecAvantCreation):
        await _driver(tmp_path, script).provision(_spec())


async def test_echec_sans_json_est_indetermine(tmp_path: Path) -> None:
    """Un driver qui meurt sans dernière ligne JSON ne dit pas ce qu'il a
    laissé : jamais de rejeu automatique."""
    script = "#!/usr/bin/env bash\necho 'segfault' >&2\nexit 139\n"
    with pytest.raises(Indetermine):
        await _driver(tmp_path, script).provision(_spec())


async def test_timeout_est_indetermine(tmp_path: Path) -> None:
    """Un timeout en plein apply ne dit pas si la ressource a été créée."""
    script = "#!/usr/bin/env bash\nsleep 30\n"
    with pytest.raises(Indetermine):
        await _driver(tmp_path, script, timeout_s=0.2).provision(_spec())
