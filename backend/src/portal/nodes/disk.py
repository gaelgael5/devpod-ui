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


async def probe_host(host: HostConfig) -> tuple[int, int, int, int] | None:
    """Mesure l'occupation disque d'un host. None si injoignable/illisible."""
    from ..devpod.host_exec import run_host_command

    rc, out, err = await run_host_command(host, DF_COMMAND, timeout=PROBE_TIMEOUT_S)
    if rc != 0:
        raise RuntimeError((err or out or f"df rc={rc}").strip()[:200])
    return parse_df(out)


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
            total, used, avail, pct = res
            await host_disk_db.record_usage(
                conn, name, total=total, used=used, avail=avail, used_pct=pct, now=now
            )
            if pct >= warn_pct:
                _log.warning(
                    "host_disk_high", host=name, used_pct=pct, avail_bytes=avail, threshold=warn_pct
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
