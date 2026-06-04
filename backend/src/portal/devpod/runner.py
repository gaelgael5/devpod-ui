from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

# Registre des verrous par ws_id
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(ws_id: str) -> asyncio.Lock:
    if ws_id not in _locks:
        _locks[ws_id] = asyncio.Lock()
    return _locks[ws_id]


def clear_locks() -> None:
    """Vide le registre de verrous. Usage tests uniquement."""
    _locks.clear()


async def run_subprocess(
    cmd: list[str],
    env: dict[str, str],
    log_path: Path,
    ws_id: str,
) -> int:
    """
    Exécute une commande devpod en async, streame stdout+stderr vers log_path.
    Acquiert un verrou par ws_id pour sérialiser les opérations sur le même workspace.
    Jamais bloquant : asyncio.create_subprocess_exec + lecture ligne par ligne.
    """
    async with _get_lock(ws_id):
        _log.info("devpod_subprocess_start", ws_id=ws_id, cmd=cmd[0] if cmd else "")
        log_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        assert proc.stdout is not None
        with log_path.open("w", encoding="utf-8") as log_file:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace")
                log_file.write(decoded)
                log_file.flush()

        returncode = await proc.wait()
        _log.info("devpod_subprocess_done", ws_id=ws_id, returncode=returncode)
        return returncode
