"""Occupation disque des hosts, posée par la sonde horaire (nodes/disk.py).

Absence de ligne = jamais sondé. `error` non nul = dernière sonde en échec (la
mesure précédente est alors conservée : un host momentanément injoignable ne doit
pas faire disparaître son dernier taux connu de l'écran).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import host_disk


async def get_all(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    rows = (await conn.execute(select(host_disk))).mappings().all()
    return {r["name"]: dict(r) for r in rows}


async def record_usage(
    conn: AsyncConnection, name: str, metrics: dict[str, Any], now: datetime
) -> None:
    """Enregistre une mesure réussie (efface l'erreur précédente).

    Mémoire et CPU sont optionnels : un noyau dont `/proc/meminfo` est illisible
    ne doit pas faire perdre le taux de remplissage disque, qui porte l'alerte.
    """
    values: dict[str, Any] = {
        "name": name,
        "total_bytes": metrics["total"],
        "used_bytes": metrics["used"],
        "avail_bytes": metrics["avail"],
        "used_pct": metrics["used_pct"],
        "mem_total_bytes": metrics.get("mem_total"),
        "mem_used_bytes": metrics.get("mem_used"),
        "mem_pct": metrics.get("mem_pct"),
        "cpu_pct": metrics.get("cpu_pct"),
        "cpu_cores": metrics.get("cpu_cores"),
        "error": None,
        "measured_at": now,
    }
    await conn.execute(
        pg_insert(host_disk)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["name"], set_={k: v for k, v in values.items() if k != "name"}
        )
    )


async def record_error(conn: AsyncConnection, name: str, error: str, now: datetime) -> None:
    """Marque la sonde en échec SANS effacer la dernière mesure connue.

    Un host injoignable une heure ne doit pas faire disparaître son taux de
    l'écran : on garde la valeur, on l'accompagne de l'erreur et de sa date pour
    que l'UI puisse la présenter comme périmée plutôt que comme absente.
    """
    await conn.execute(
        pg_insert(host_disk)
        .values(name=name, error=error[:500], measured_at=now)
        .on_conflict_do_update(
            index_elements=["name"], set_={"error": error[:500], "measured_at": now}
        )
    )


async def prune_absent(conn: AsyncConnection, known: set[str]) -> None:
    """Supprime les lignes des hosts retirés de la config."""
    if known:
        await conn.execute(delete(host_disk).where(host_disk.c.name.notin_(known)))
    else:
        await conn.execute(delete(host_disk))
