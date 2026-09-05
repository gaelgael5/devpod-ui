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
import contextlib
import json
import os
import signal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import ValidationError

from .contract import MachineDescriptor, MachineSpec
from .errors import DriverError, EchecApresCreation, EchecAvantCreation, Indetermine

_log = structlog.get_logger(__name__)

_TIMEOUT_DEFAULT_S = 1800.0


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

    def __init__(
        self,
        executable: Path,
        timeout_s: float = _TIMEOUT_DEFAULT_S,
        provider_type: str = "",
    ) -> None:
        self._executable = executable
        # Le timeout est une propriété du DRIVER : un qm clone et un apply
        # cloud n'ont pas le même horizon raisonnable.
        self._timeout_s = timeout_s
        self._provider_type = provider_type

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

    def _classifier_echec(
        self, action: str, rc: int | None, stdout: bytes, err_text: str
    ) -> DriverError:
        """Classe un rc ≠ 0 selon ce que le driver a laissé derrière lui.

        Contrat du protocole : en échec, le driver émet en DERNIÈRE ligne de
        stdout un objet `{"status":"error","stage":...,"provider_ref":{...}}`
        où `provider_ref` n'est présent que si la machine existe. Sans cette
        ligne, l'issue est inconnue — `Indetermine`, pas de rejeu automatique.
        """
        detail = f"rc={rc} — {err_text[-500:] or '<stderr vide>'}"
        erreur = _derniere_ligne_json(stdout)
        if erreur is None or erreur.get("status") != "error":
            return Indetermine(
                f"driver {self._executable.name} : {action} interrompu sans ligne "
                f"d'erreur JSON — issue inconnue ({detail})"
            )
        stage = str(erreur.get("stage") or "?")
        message = str(erreur.get("message") or detail)
        ref = erreur.get("provider_ref")
        if isinstance(ref, dict) and ref:
            return EchecApresCreation(
                f"driver {self._executable.name} : échec à l'étape {stage} — "
                f"machine créée, configuration incomplète ({message})",
                provider_ref=ref,
                provider=self._provider_type,
            )
        return EchecAvantCreation(
            f"driver {self._executable.name} : échec à l'étape {stage} avant toute "
            f"création ({message})"
        )

    async def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        # start_new_session : le driver peut engendrer des enfants (un apply
        # OpenTofu lance ses providers) — au timeout, on tue le GROUPE entier,
        # sinon un petit-fils garde les pipes ouverts et survit au kill.
        proc = await asyncio.create_subprocess_exec(
            str(self._executable),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps(request).encode()),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            await proc.wait()
            # Un timeout en plein apply ne dit pas si la ressource a été
            # créée : jamais de rejeu automatique.
            raise Indetermine(
                f"driver {self._executable.name} : délai dépassé "
                f"({self._timeout_s:.0f}s) sur {request['action']} — issue inconnue"
            ) from None
        err_text = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            _log.warning(
                "provisioning_driver_failed",
                driver=self._executable.name,
                action=request["action"],
                rc=proc.returncode,
            )
            raise self._classifier_echec(request["action"], proc.returncode, stdout, err_text)
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


def _derniere_ligne_json(stdout: bytes) -> dict[str, Any] | None:
    """Dernière ligne de stdout qui parse en objet JSON — même contrat que le
    `parse_last_json` du portail côté scripts."""
    for line in reversed(stdout.decode(errors="replace").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    return None
