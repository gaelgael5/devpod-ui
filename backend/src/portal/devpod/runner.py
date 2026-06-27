from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path

import structlog

# Séquences d'échappement ANSI (couleurs, mise en forme) émises par devpod --debug.
_ANSI_RE = re.compile(r"\x1b\[[\d;]*[mGKHF]")

_log = structlog.get_logger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_processes: dict[str, asyncio.subprocess.Process] = {}


def _get_lock(ws_id: str) -> asyncio.Lock:
    return _locks.setdefault(ws_id, asyncio.Lock())


def clear_locks() -> None:
    """Vide le registre de verrous. Usage tests uniquement."""
    _locks.clear()


async def kill_if_running(ws_id: str) -> None:
    """Tue le subprocess devpod actif pour ws_id s'il existe, libérant le verrou."""
    proc = _processes.get(ws_id)
    if proc is None or proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
        await proc.wait()
    _log.info("devpod_subprocess_killed", ws_id=ws_id)


async def run_subprocess(
    cmd: list[str],
    env: dict[str, str],
    log_path: Path,
    ws_id: str,
    timeout_s: int | None = None,
) -> int:
    """
    Exécute une commande devpod en async, streame stdout+stderr vers log_path.
    Acquiert un verrou par ws_id pour sérialiser les opérations sur le même workspace.
    Si timeout_s est fourni, tue le process et lève TimeoutError après ce délai.
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
        _processes[ws_id] = proc
        returncode: int = -1
        try:
            if proc.stdout is None:
                raise RuntimeError(f"subprocess stdout pipe not available for ws_id={ws_id!r}")

            _timeout = (
                asyncio.timeout(timeout_s) if timeout_s is not None else contextlib.nullcontext()
            )
            try:
                async with _timeout:
                    with log_path.open("w", encoding="utf-8") as log_file:
                        while True:
                            line = await proc.stdout.readline()
                            if not line:
                                break
                            decoded = _ANSI_RE.sub("", line.decode(errors="replace"))
                            log_file.write(decoded)
                            log_file.flush()
                    returncode = await proc.wait()
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                    await proc.wait()
                _log.warning("devpod_subprocess_timeout", ws_id=ws_id, timeout_s=timeout_s)
                raise
        finally:
            _processes.pop(ws_id, None)

        _log.info("devpod_subprocess_done", ws_id=ws_id, returncode=returncode)
        return returncode
