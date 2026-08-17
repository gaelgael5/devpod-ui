"""Sonde d'occupation disque des hosts — passe horaire.

Motivation (incident du 17/08) : `host-dev-01` est arrivé à 100 % — zéro bloc
libre, écritures en échec — sans qu'aucun écran ne le signale. On ne s'en est
aperçu qu'en cherchant la cause d'autre chose. La saturation disque est pourtant
prévisible : elle se voit venir des heures à l'avance.

La mesure porte sur la partition qui compte réellement : celle qui héberge les
données Docker (images des devcontainers, conteneurs, volumes) et les
répertoires de travail devpod. C'est elle qui se remplit, pas `/boot`.

Sonde best-effort et non bloquante : un host injoignable conserve sa dernière
mesure, accompagnée de l'erreur (cf. db/host_disk.record_error).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from ..config.models import HostConfig
from ..db import host_disk as host_disk_db
from ..db.global_config import get_optional_cached_global
from ..settings import get_settings

_log = structlog.get_logger(__name__)

# `df -P` (POSIX) garantit UNE ligne par système de fichiers, non coupée quand le
# nom du device est long — le format par défaut passe à la ligne et casse le
# parsing. `-B1` donne des octets bruts : pas d'unités à ré-interpréter.
DF_COMMAND = "df -PB1 /var/lib/docker 2>/dev/null || df -PB1 /"

# Disque + mémoire + charge CPU en UNE seule connexion : la sonde coûte alors
# exactement le même SSH qu'avant. Sections délimitées pour un parsing sans
# ambiguïté. `/proc/meminfo` plutôt que `free` (format stable, pas de locale) ;
# `/proc/loadavg` + `nproc` pour ramener la charge à un pourcentage comparable
# d'une machine à l'autre.
METRICS_COMMAND = (
    "echo '@@DF'; " + DF_COMMAND + "; "
    "echo '@@MEM'; cat /proc/meminfo 2>/dev/null | head -5; "
    "echo '@@CPU'; cat /proc/loadavg 2>/dev/null; nproc 2>/dev/null || echo 1"
)

# Timeout court : la sonde ne doit pas retenir un slot d'exécution du host.
PROBE_TIMEOUT_S = 20.0


def parse_df(output: str) -> tuple[int, int, int, int] | None:
    """`(total, used, avail, used_pct)` depuis une sortie `df -PB1`, ou None.

    On lit la DERNIÈRE ligne non vide : `df` émet un en-tête, et le fallback
    `||` peut en produire deux si la première commande a écrit malgré tout.
    Le pourcentage est RECALCULÉ depuis les octets plutôt que lu dans la colonne
    `Capacity` : `df` y arrondit à l'entier supérieur et compte la réserve root,
    ce qui affiche « 100% » alors qu'il reste de la place — trop imprécis pour
    piloter un seuil d'alerte.
    """
    lines = [ln for ln in output.splitlines() if ln.strip()]
    if not lines:
        return None
    for line in reversed(lines):
        parts = line.split()
        # Filesystem 1B-blocks Used Available Capacity Mounted-on
        if len(parts) < 6 or not parts[1].isdigit():
            continue
        try:
            total, used, avail = int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            continue
        if total <= 0:
            return None
        return total, used, avail, round(used * 100 / total)
    return None


def parse_meminfo(block: str) -> tuple[int, int] | None:
    """`(total_bytes, used_bytes)` depuis `/proc/meminfo`, ou None.

    « Utilisé » = total − **MemAvailable**, pas total − MemFree : le cache et les
    buffers sont récupérables à la demande, les compter comme occupés afficherait
    ~95 % sur une machine parfaitement saine. MemAvailable est l'estimation que
    fait le noyau lui-même de ce qui reste réellement allouable.
    """
    values: dict[str, int] = {}
    for line in block.splitlines():
        parts = line.split(":")
        if len(parts) != 2:
            continue
        num = parts[1].strip().split()
        if num and num[0].isdigit():
            values[parts[0].strip()] = int(num[0]) * 1024  # meminfo est en kB
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return total, max(0, total - available)


def parse_loadavg(block: str) -> tuple[float, int] | None:
    """`(charge_1min, nb_cœurs)` depuis `/proc/loadavg` + `nproc`, ou None."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    try:
        load1 = float(lines[0].split()[0])
        cores = max(1, int(lines[-1].strip()))
    except (ValueError, IndexError):
        return None
    return load1, cores


def _section(out: str, name: str) -> str:
    """Contenu d'une section `@@NOM` de la sortie de METRICS_COMMAND."""
    marker = f"@@{name}"
    if marker not in out:
        return ""
    rest = out.split(marker, 1)[1]
    return rest.split("@@", 1)[0]


async def probe_host(host: HostConfig) -> dict[str, Any] | None:
    """Mesure disque + mémoire + charge d'un host. None si le disque est illisible.

    Le disque est la mesure PIVOT : sans lui la sonde est un échec. Mémoire et
    charge sont optionnelles — un noyau sans `/proc/meminfo` exploitable ne doit
    pas faire perdre le taux de remplissage, qui est l'alerte importante.
    """
    from ..devpod.host_exec import run_host_command

    rc, out, err = await run_host_command(host, METRICS_COMMAND, timeout=PROBE_TIMEOUT_S)
    if rc != 0:
        raise RuntimeError((err or out or f"sonde rc={rc}").strip()[:200])

    disk = parse_df(_section(out, "DF") or out)
    if disk is None:
        return None
    total, used, avail, pct = disk
    metrics: dict[str, Any] = {
        "total": total,
        "used": used,
        "avail": avail,
        "used_pct": pct,
        "mem_total": None,
        "mem_used": None,
        "mem_pct": None,
        "cpu_pct": None,
        "cpu_cores": None,
    }

    mem = parse_meminfo(_section(out, "MEM"))
    if mem is not None:
        mem_total, mem_used = mem
        metrics["mem_total"] = mem_total
        metrics["mem_used"] = mem_used
        metrics["mem_pct"] = round(mem_used * 100 / mem_total)

    cpu = parse_loadavg(_section(out, "CPU"))
    if cpu is not None:
        load1, cores = cpu
        metrics["cpu_cores"] = cores
        # Charge ramenée au nombre de cœurs : 100 % = tous les cœurs saturés.
        # Bornée à 999 — une charge d'attente d'E/S peut exploser sans que la
        # valeur brute dise quoi que ce soit d'utile au-delà.
        metrics["cpu_pct"] = min(999, round(load1 * 100 / cores))

    return metrics


async def run_disk_pass() -> None:
    """Une passe : sonde tous les hosts SSH enrôlés, persiste le résultat.

    Les sondes réseau sont lancées AVANT d'acquérir la connexion DB — aucune
    connexion du pool n'est retenue pendant les timeouts (même règle que la
    sonde de vivacité et le monitor MCP).
    """
    cfg = get_optional_cached_global()
    if cfg is None:
        return
    # `type == "ssh"` : seuls les hosts joignables par notre canal d'exécution.
    # Les VM de test éphémères sont incluses — elles saturent tout autant, et
    # c'est justement là que les stacks compose s'empilent.
    hosts = [h for h in cfg.hosts if h.type == "ssh" and h.address and h.host_cert_slug]
    if not hosts:
        return

    async def _one(h: HostConfig) -> tuple[str, object]:
        try:
            return h.name, await probe_host(h)
        except Exception as exc:  # noqa: BLE001 — best-effort, l'erreur est persistée
            return h.name, exc

    results = await asyncio.gather(*[_one(h) for h in hosts])

    now = datetime.now(UTC)
    warn_pct = get_settings().host_disk_warn_pct
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        for name, res in results:
            if isinstance(res, Exception):
                await host_disk_db.record_error(conn, name, str(res), now)
                _log.warning("host_disk_probe_failed", host=name, error=str(res))
                continue
            if res is None:
                await host_disk_db.record_error(conn, name, "sortie df illisible", now)
                continue
            pct = int(res["used_pct"])
            await host_disk_db.record_usage(conn, name, res, now)
            if pct >= warn_pct:
                _log.warning(
                    "host_disk_high",
                    host=name,
                    used_pct=pct,
                    avail_bytes=res["avail"],
                    threshold=warn_pct,
                )
        await host_disk_db.prune_absent(conn, {h.name for h in hosts})


async def disk_loop() -> None:
    """Boucle de fond : une passe toutes les `host_disk_interval_s` (1 h par défaut)."""
    interval = get_settings().host_disk_interval_s
    while True:
        try:
            await run_disk_pass()
        except Exception as exc:  # noqa: BLE001 — une boucle de fond ne doit jamais mourir
            _log.exception("host_disk_pass_failed", error=str(exc))
        await asyncio.sleep(interval)
