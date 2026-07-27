"""Sonde de vivacité des hosts (enabler 727ee81d).

Boucle périodique dédiée, découplée du polling du front et du SSH éphémère par
requête (le mécanisme qui a saturé pendant l'incident du 24/07) : un simple TCP
connect sur le port de pilotage du host — port du daemon pour docker-tls, 22
pour ssh. Hystérésis à la descente (`threshold` échecs consécutifs avant de
basculer `unreachable`), remontée à la première réussite.

L'alerte est une ligne de log structurée `host_reachability_changed` émise sur
TRANSITION uniquement (jamais à chaque tick) : la règle d'alerte Grafana se
branche dessus vers le contact point existant. L'état persiste dans
`host_health` et alimente `node_list` (health.reachable / last_seen).

Les hosts `usage=tests` (VM éphémères, créées/détruites au fil des workspaces)
ne sont pas sondés : leurs allers-retours noieraient l'alerte.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..db import host_health as host_health_db
from ..db.global_config import get_optional_cached_global
from ..settings import get_settings

_log = structlog.get_logger(__name__)

_CONNECT_TIMEOUT_S = 5.0
_DEFAULT_DOCKER_PORT = 2376

CheckFn = Callable[[str, int], Awaitable[bool]]

# Échecs consécutifs par host (l'hystérésis). Volontairement en mémoire : après
# un restart du portail il faut re-cumuler N échecs avant d'alerter — l'état
# persisté (`host_health.reachable`), lui, survit.
_failures: dict[str, int] = {}


def reset_state() -> None:
    """Réinitialise l'hystérésis. Réservé aux tests."""
    _failures.clear()


def probe_target(host: HostConfig) -> tuple[str, int] | None:
    """(hôte, port) à sonder — None si le host n'a pas d'adresse exploitable."""
    if host.type == "docker-tls" and host.docker_host:
        from urllib.parse import urlsplit

        parts = urlsplit(host.docker_host)  # tcp://ip:2376
        if parts.hostname:
            return parts.hostname, parts.port or _DEFAULT_DOCKER_PORT
        return None
    if host.type == "ssh" and host.address:
        hostname = host.address.rsplit("@", 1)[-1]
        return (hostname, 22) if hostname else None
    return None


def evaluate(
    prev: bool | None, failures: int, *, ok: bool, threshold: int
) -> tuple[bool | None, int]:
    """(transition à persister ou None si inchangé, nouveau compteur d'échecs).

    - Réussite : remontée immédiate dès que l'état persisté n'était pas `reachable`.
    - Échec : bascule `unreachable` seulement après `threshold` échecs consécutifs,
      pour ne pas alerter sur un hoquet réseau d'un tick.
    """
    if ok:
        return (True if prev is not True else None), 0
    failures += 1
    if prev is not False and failures >= threshold:
        return False, failures
    return None, failures


async def tcp_check(hostname: str, port: int) -> bool:
    """Check L4 léger : TCP connect, sans le moindre octet applicatif."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port), _CONNECT_TIMEOUT_S
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


async def run_liveness_pass(
    *,
    conn: AsyncConnection | None = None,
    check_fn: CheckFn = tcp_check,
    threshold: int | None = None,
) -> None:
    """Une passe complète : sonde tous les hosts, applique l'hystérésis, persiste.

    Les checks réseau sont exécutés AVANT d'acquérir la moindre connexion DB —
    aucune connexion du pool n'est tenue pendant les timeouts de sonde (même
    règle que le monitor MCP, bug 026). `conn` explicite : tests uniquement.
    """
    cfg = get_optional_cached_global()
    if cfg is None:
        return
    if threshold is None:
        threshold = get_settings().host_liveness_failures

    probed = [
        (h.name, target)
        for h in cfg.hosts
        if h.usage != "tests" and (target := probe_target(h)) is not None
    ]
    results = list(
        await asyncio.gather(*[check_fn(hostname, port) for _, (hostname, port) in probed])
    )

    if conn is not None:
        await _apply(conn, probed, results, threshold)
        return
    from ..db.engine import _get_engine

    async with _get_engine().begin() as fresh_conn:
        await _apply(fresh_conn, probed, results, threshold)


async def _apply(
    conn: AsyncConnection,
    probed: list[tuple[str, tuple[str, int]]],
    results: list[bool],
    threshold: int,
) -> None:
    prev_rows = await host_health_db.get_all(conn)
    now = datetime.now(UTC)
    for (name, _), ok in zip(probed, results, strict=True):
        prev = prev_rows.get(name, {}).get("reachable")
        transition, _failures[name] = evaluate(
            prev, _failures.get(name, 0), ok=bool(ok), threshold=threshold
        )
        if ok:
            await host_health_db.record_success(
                conn, name, now, transitioned=transition is True
            )
        elif transition is False:
            await host_health_db.record_unreachable(conn, name, now)
        if transition is True:
            _log.info("host_reachability_changed", host=name, state="reachable")
        elif transition is False:
            _log.warning(
                "host_reachability_changed",
                host=name,
                state="unreachable",
                consecutive_failures=_failures[name],
            )

    # Hosts retirés de la config : purge de l'état persisté et de l'hystérésis.
    known = {name for name, _ in probed}
    await host_health_db.prune_absent(conn, known)
    for stale in set(_failures) - known:
        del _failures[stale]


async def liveness_loop() -> None:
    """Boucle de fond : sonde tous les hosts toutes les host_liveness_interval_s."""
    interval = get_settings().host_liveness_interval_s
    while True:
        try:
            await run_liveness_pass()
        except Exception as exc:  # noqa: BLE001 — une boucle de fond ne doit jamais mourir
            _log.exception("host_liveness_pass_failed", error=str(exc))
        await asyncio.sleep(interval)
