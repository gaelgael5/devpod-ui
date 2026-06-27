"""Détection de conflit et suggestion de port hôte (spec 26 §7)."""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..devpod.host_exec import run_host_command
from .db import conflicting_ports

_LISTEN_RE = re.compile(r":(\d{2,5})\s")


class PortConflict(Exception):
    def __init__(self, conflicts: set[int], suggestion: int | None) -> None:
        self.conflicts = conflicts
        self.suggestion = suggestion
        super().__init__(f"ports en conflit: {sorted(conflicts)} (libre suggéré: {suggestion})")


def suggest_free_port(occupied: set[int], start: int = 3000, end: int = 9999) -> int | None:
    for p in range(start, end + 1):
        if p not in occupied:
            return p
    return None


async def _live_used_ports(host: HostConfig) -> set[int]:
    """Ports en écoute sur le nœud (best-effort ; échec silencieux)."""
    try:
        rc, out, _ = await run_host_command(host, "ss -ltn 2>/dev/null || true", timeout=15.0)
    except Exception:
        return set()
    if rc != 0:
        return set()
    return {int(m) for m in _LISTEN_RE.findall(out) if m.isdigit()}


async def check_ports(
    conn: AsyncConnection, host: HostConfig, node_id: str, ports: list[int]
) -> None:
    if not ports:
        return
    db_conflicts = await conflicting_ports(conn, node_id, ports)
    live = await _live_used_ports(host)
    live_conflicts = set(ports) & live
    conflicts = db_conflicts | live_conflicts
    if conflicts:
        occupied = db_conflicts | live | set(ports)
        raise PortConflict(conflicts, suggest_free_port(occupied))
