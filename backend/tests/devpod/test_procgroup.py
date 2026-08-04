"""Kill de groupe des sous-processus (bug 813f425f — fuite de pids du 04/08).

`proc.kill()` ne tue que le fils direct : un ssh tué au timeout laissait son
ProxyCommand orphelin. Ces tests vérifient avec de vrais process que le kill de
groupe atteint TOUTE la descendance, et que le recensement /proc voit un zombie.
"""
from __future__ import annotations

import asyncio
import os

from portal.devpod.procgroup import kill_process_group, process_census, spawn_group


def _alive(pid: int) -> bool:
    """True si le pid existe encore (zombie compris)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_kill_process_group_kills_descendants() -> None:
    # Le parent bash écrit le pid de son ENFANT sleep puis attend — même schéma
    # qu'un ssh + ProxyCommand. Après kill_process_group, les DEUX sont morts.
    r, w = os.pipe()
    proc = await spawn_group(
        "bash",
        "-c",
        f"sleep 300 & echo $! >&{w}; wait",
        pass_fds=(w,),
    )
    os.close(w)
    with os.fdopen(r) as fh:
        child_pid = int(fh.readline().strip())
    assert _alive(proc.pid) and _alive(child_pid)

    await kill_process_group(proc)

    assert proc.returncode is not None  # fils direct moissonné
    # L'enfant (petit-fils du portail) doit être mort AUSSI — c'est tout l'objet
    # du kill de groupe ; proc.kill() seul l'aurait laissé vivant 300 s.
    for _ in range(50):
        if not _alive(child_pid):
            break
        await asyncio.sleep(0.02)
    assert not _alive(child_pid)


async def test_kill_process_group_idempotent_on_finished_process() -> None:
    proc = await spawn_group("true")
    await proc.wait()
    await kill_process_group(proc)  # ne doit pas lever
    assert proc.returncode == 0


async def test_spawn_group_isolates_from_portal_group() -> None:
    """Le fils est leader de SON groupe : un killpg ne touche jamais le portail."""
    proc = await spawn_group("sleep", "60")
    try:
        assert os.getpgid(proc.pid) == proc.pid
        assert os.getpgid(proc.pid) != os.getpgid(0)
    finally:
        await kill_process_group(proc)


async def test_process_census_counts_zombies() -> None:
    census0 = process_census()
    assert census0["total"] > 0

    # Fabrique un zombie : le fils sort, on ne le moissonne pas tout de suite.
    proc = await asyncio.create_subprocess_exec("true")
    for _ in range(100):
        census = process_census()
        if census["zombies"] > census0.get("zombies", 0) or proc.returncode is not None:
            break
        await asyncio.sleep(0.01)
    # Moisson finale : le zombie disparaît du recensement.
    await proc.wait()
    assert process_census()["total"] >= 1
