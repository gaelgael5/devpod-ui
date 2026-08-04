"""Sous-processus en groupe dédié + kill de tout le groupe (bug 813f425f).

`proc.kill()` ne tue que le processus direct : un `ssh` tué au timeout laissait
son `ProxyCommand` (`devpod ssh --stdio`, qui spawne lui-même docker/ssh) orphelin
— re-parenté au PID 1 du conteneur, vivant s'il pendait, zombie à sa mort. Les
spawns passent donc par `start_new_session=True` (le fils devient leader d'un
groupe de processus neuf) et le nettoyage par `kill_process_group` (SIGKILL au
groupe entier, puis moisson du fils direct).

Les masters ControlMaster ne sont PAS affectés : ssh les détache par `setsid`
dans leur propre session — un kill de groupe ne touche jamais un master partagé.
La moisson des orphelins restants (masters expirés…) relève de `init: true`
dans le compose (tini en PID 1).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

import structlog

_log = structlog.get_logger(__name__)


async def spawn_group(*argv: str, **kwargs: object) -> asyncio.subprocess.Process:
    """`create_subprocess_exec` avec groupe de processus dédié.

    Mêmes kwargs que `asyncio.create_subprocess_exec` ; force
    `start_new_session=True` pour que `kill_process_group` puisse atteindre
    toute la descendance (ProxyCommand compris).
    """
    kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(*argv, **kwargs)  # type: ignore[arg-type]


async def kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL au groupe entier du processus, puis moisson du fils direct.

    Sans effet si le groupe est déjà mort. À utiliser sur les chemins de
    timeout/annulation à la place de `proc.kill()` : celui-ci laissait vivre la
    descendance (ProxyCommand, docker, ssh imbriqués).
    """
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        # Repli : si le groupe a déjà disparu mais pas le fils (course rare).
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()


def process_census() -> dict[str, int]:
    """(total, zombies) des processus visibles dans /proc — observabilité 813f425f.

    Un compteur qui monte sans redescendre = fuite (la panne du 04/08 a saturé
    `pids-limit` en silence) ; les zombies comptent dans la limite pids du cgroup.
    Léger : un scan de /proc, aucune commande externe.
    """
    total = 0
    zombies = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        total += 1
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as f:
                # Champ 3 (state), après le nom entre parenthèses (peut contenir des espaces).
                stat = f.read()
            if stat.rpartition(")")[2].split()[0] == "Z":
                zombies += 1
        except OSError:
            continue  # process disparu entre le listdir et la lecture
    return {"total": total, "zombies": zombies}
