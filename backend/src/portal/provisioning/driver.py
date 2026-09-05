"""Interface de driver de provisionnement et protocole exécutable.

Deux formes de driver, un seul contrat :

- un **module Python** qui satisfait `ProvisioningDriver` ;
- un **exécutable** qui lit un JSON sur stdin et écrit un JSON sur stdout
  (`ExecutableDriver` en est l'adaptateur). Ce second protocole est *le*
  protocole de référence : il permet à un utilisateur auto-hébergé d'écrire un
  driver pour son hyperviseur exotique en shell, sans toucher au portail.

Protocole exécutable :

- provision : stdin `{"action": "provision", "spec": {...MachineSpec...}}`
              stdout un `MachineDescriptor` JSON, code retour 0 ;
- destroy   : stdin `{"action": "destroy", "provider_ref": {...}}`
              stdout `{"status": "ok"}`, code retour 0.

stdout est réservé au JSON de réponse ; les journaux vont sur stderr. Un code
retour non nul est une erreur, stderr en porte la raison.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import ValidationError

from .contract import MachineDescriptor, MachineSpec

_log = structlog.get_logger(__name__)

_TIMEOUT_DEFAULT_S = 1800.0


class DriverError(RuntimeError):
    """Échec d'un driver de provisionnement (raison humaine dans le message)."""


@runtime_checkable
class ProvisioningDriver(Protocol):
    """Le contrat : deux opérations, rien d'autre n'engage le portail."""

    async def provision(self, spec: MachineSpec) -> MachineDescriptor: ...

    async def destroy(self, provider_ref: dict[str, Any]) -> None: ...


_REGISTRY: dict[str, ProvisioningDriver] = {}


def register_driver(provider_type: str, driver: ProvisioningDriver) -> None:
    """Enregistre le driver servant les specs dont `provider.type` vaut
    `provider_type`. Le dernier enregistré gagne (surcharge en test)."""
    _REGISTRY[provider_type] = driver


def driver_for(provider_type: str) -> ProvisioningDriver:
    driver = _REGISTRY.get(provider_type)
    if driver is None:
        raise DriverError(
            f"aucun driver enregistré pour le provider {provider_type!r} "
            f"(connus : {sorted(_REGISTRY) or 'aucun'})"
        )
    return driver


class ExecutableDriver:
    """Adaptateur du protocole exécutable JSON stdin/stdout."""

    def __init__(self, executable: Path, timeout_s: float = _TIMEOUT_DEFAULT_S) -> None:
        self._executable = executable
        self._timeout_s = timeout_s

    async def provision(self, spec: MachineSpec) -> MachineDescriptor:
        raw = await self._run({"action": "provision", "spec": spec.model_dump()})
        try:
            return MachineDescriptor.model_validate(raw)
        except ValidationError as exc:
            raise DriverError(
                f"driver {self._executable.name} : descripteur invalide — {exc}"
            ) from exc

    async def destroy(self, provider_ref: dict[str, Any]) -> None:
        raw = await self._run({"action": "destroy", "provider_ref": provider_ref})
        if raw.get("status") != "ok":
            raise DriverError(
                f"driver {self._executable.name} : destroy a rendu {raw.get('status')!r}"
            )

    async def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            str(self._executable),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps(request).encode()),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise DriverError(
                f"driver {self._executable.name} : délai dépassé "
                f"({self._timeout_s:.0f}s) sur {request['action']}"
            ) from None
        err_text = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            _log.warning(
                "provisioning_driver_failed",
                driver=self._executable.name,
                action=request["action"],
                rc=proc.returncode,
            )
            raise DriverError(
                f"driver {self._executable.name} : rc={proc.returncode} — "
                f"{err_text[-500:] or '<stderr vide>'}"
            )
        try:
            payload = json.loads(stdout.decode())
        except ValueError as exc:
            raise DriverError(
                f"driver {self._executable.name} : stdout n'est pas du JSON "
                f"(les journaux vont sur stderr) — {stdout[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise DriverError(
                f"driver {self._executable.name} : la réponse doit être un objet JSON"
            )
        return payload
