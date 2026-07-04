"""Bug 038 : le sous-process ssh-agent démarré pour le forwarding git SSH doit
être tuable indépendamment du succès du parsing de sa sortie.

Avec `ssh-agent -s` seul (sans -D), le process lancé daemonise : il imprime les
variables d'env PUIS SORT IMMÉDIATEMENT, le vrai agent tournant en arrière-plan
sous un PID différent, jamais capturé par le handle du subprocess — le tuer ne
fait rien. Avec `-D` (foreground), le process lancé EST l'agent réel tout du
long : son PID (agent_proc.pid) est le vrai PID, tuable directement.

Ces tests exercent le vrai binaire ssh-agent (pas de mock) : c'est le mécanisme
lui-même qui est sous test, pas la logique métier de _run_up_task.
"""
from __future__ import annotations

import asyncio
import os
import re

import pytest


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    else:
        return True


@pytest.mark.asyncio
async def test_ssh_agent_without_dash_d_daemonizes_launcher_exits() -> None:
    """Caractérise le bug : sans -D, le subprocess lancé sort immédiatement
    (le vrai agent est un process détaché différent)."""
    proc = await asyncio.create_subprocess_exec(
        "ssh-agent", "-s",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert proc.returncode == 0  # le lanceur est déjà sorti — daemonisé

    pid_match = re.search(r"SSH_AGENT_PID=(\d+);", stdout.decode())
    assert pid_match is not None
    real_agent_pid = int(pid_match.group(1))
    assert real_agent_pid != proc.pid  # PID différent : tuer proc ne tuerait pas l'agent réel

    # Nettoyage : l'agent détaché doit être tué explicitement (sinon fuite dans CE test).
    if _pid_alive(real_agent_pid):
        os.kill(real_agent_pid, 9)


@pytest.mark.asyncio
async def test_ssh_agent_with_dash_d_proc_pid_is_the_real_agent_and_killable() -> None:
    """Le fix (bug 038) : avec -D, agent_proc.pid EST le vrai PID de l'agent, et
    le tuer directement l'arrête réellement — indépendamment du parsing."""
    proc = await asyncio.create_subprocess_exec(
        "ssh-agent", "-s", "-D",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    first_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
    sock_match = re.search(r"SSH_AUTH_SOCK=([^;]+);", first_line.decode())
    assert sock_match is not None

    assert _pid_alive(proc.pid)  # l'agent tourne réellement sous ce PID

    proc.kill()
    await asyncio.wait_for(proc.wait(), timeout=5.0)

    assert not _pid_alive(proc.pid)  # tué pour de vrai, pas un no-op sur un lanceur déjà sorti


@pytest.mark.asyncio
async def test_ssh_agent_with_dash_d_killable_even_if_output_unparsable() -> None:
    """Le point précis du bug 038 : même si le parsing de la sortie échoue, le
    process (avec -D) reste tuable via son PID, sans dépendre du parsing."""
    proc = await asyncio.create_subprocess_exec(
        "ssh-agent", "-s", "-D",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert _pid_alive(proc.pid)

    # On ignore délibérément la sortie (simulateur d'un parsing qui échoue) et on
    # tue quand même directement via le handle — c'est exactement le correctif.
    proc.kill()
    await asyncio.wait_for(proc.wait(), timeout=5.0)

    assert not _pid_alive(proc.pid)
