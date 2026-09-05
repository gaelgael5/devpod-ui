"""Driver « existing » — enrôler une machine déjà là (ticket 5).

Le test du contrat : un driver qui ne crée rien rend exactement le même objet
que les autres. Il valide seulement que la machine répond au SSH par clé, et
rend un descripteur à `provider_ref` vide (rien n'a été créé, rien à
référencer) et provenance inconnue.

`destroy` est un no-op : le portail ne possède pas une machine enrôlée.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import structlog

from .contract import MachineDescriptor, MachineSpec
from .driver import DriverError

_log = structlog.get_logger(__name__)

_PROBE_TIMEOUT_S = 30.0


class SshProbe(Protocol):
    async def __call__(self, *, address: str, user: str, port: int, key_path: str) -> None: ...


async def _probe_ssh(*, address: str, user: str, port: int, key_path: str) -> None:
    """Le vrai SSH par clé (pas un test de port : sshd ouvre le 22 avant que la
    clé ne soit utilisable — même leçon que l'attente A.9 du script)."""
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "LogLevel=ERROR",
        "-p",
        str(port),
    ]
    if key_path:
        argv += ["-i", key_path]
    argv += [f"{user}@{address}", "exit 0"]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise DriverError(
            f"machine {user}@{address}:{port} : SSH sans réponse après {_PROBE_TIMEOUT_S:.0f}s"
        ) from None
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[-300:] or "<stderr vide>"
        raise DriverError(f"machine {user}@{address}:{port} injoignable en SSH par clé — {detail}")


class ExistingMachineDriver:
    """`provider` attendu dans la spec : `{"type": "existing", "address": ...,
    "ssh_port"?: 22, "key_path"?: ""}` — l'utilisateur SSH est le `user` commun."""

    def __init__(self, probe: SshProbe | None = None) -> None:
        # Résolu à l'appel, pas au __init__ : un défaut-objet figerait le
        # monkeypatch en test.
        self._probe = probe

    async def provision(self, spec: MachineSpec) -> MachineDescriptor:
        address = spec.provider.get("address")
        if not isinstance(address, str) or not address:
            raise DriverError(
                "driver existing : provider.address (chaîne non vide) est obligatoire"
            )
        port = int(spec.provider.get("ssh_port", 22))
        key_path = str(spec.provider.get("key_path", ""))
        probe = self._probe or _probe_ssh
        await probe(address=address, user=spec.user, port=port, key_path=key_path)
        _log.info("existing_machine_enrolled", name=spec.name, address=address)
        return MachineDescriptor(
            address=address,
            ssh_user=spec.user,
            ssh_port=port,
            key_path=key_path,
            provider="existing",
            provider_ref={},
            hypervisor="",
        )

    async def destroy(self, provider_ref: dict[str, Any]) -> None:
        _log.info("existing_machine_destroy_noop")
