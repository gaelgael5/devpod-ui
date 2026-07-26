"""Suggestion d'arrêt des workspaces inactifs (enabler 6016436b).

**Détection + alerte uniquement — rien n'est JAMAIS arrêté automatiquement.**
L'humain tranche depuis l'UI (bouton stop existant) ou depuis l'alerte Grafana.

Critère d'inactivité (« assez bon pour proposer un bon candidat ») :
- aucun process actif en avant-plan dans les panes tmux — un shell au prompt ne
  protège PAS (c'est précisément la RAM qu'on veut récupérer), un `claude` ou un
  build en cours protège ;
- ET aucune activité tmux (`session_activity`) depuis le seuil configurable.
Un workspace joignable SANS serveur tmux est aussi candidat (rien d'actif).

Exemptions : épingle `keep_active` (jamais de suggestion), workspace non
`running`, workspace injoignable (autre problème — sonde de vivacité 727ee81d).

L'alerte est le log structuré `workspace_idle_detected`, émis UNE fois par
période d'inactivité continue (persistée en `workspace_idle`) — même chaîne que
la sonde de vivacité : une règle Grafana s'y branche, l'UI lit la même table.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import workspace_idle as workspace_idle_db
from ..db.user_config import list_workspace_refs
from ..db.workspace_status import list_all_status_db
from ..devpod.exec import NO_TMUX_SERVER_RCS, ws_exec
from ..devpod.exec import tmux as _tmux
from ..settings import get_settings

_log = structlog.get_logger(__name__)

IdleVerdict = Literal["idle", "active", "unreachable"]
ProbeFn = Callable[[str, str], Awaitable[tuple[IdleVerdict, datetime | None]]]

# Un pane dont le process d'avant-plan est un simple shell au prompt ne compte
# pas comme « actif ». Tout autre process (claude, aider, vim, make…) protège.
_IDLE_SHELLS = {"bash", "sh", "zsh", "fish", "dash", "ksh"}


async def probe_workspace_idle(
    login: str, ws_id: str
) -> tuple[IdleVerdict, datetime | None]:
    """(verdict, dernière activité tmux) d'un workspace.

    - « idle » : aucun serveur tmux, ou uniquement des shells au prompt ;
      `last_activity` = max(session_activity) si des sessions existent.
    - « active » : au moins un pane avec un process d'avant-plan non-shell.
    - « unreachable » : transport SSH mort ou timeout — on ne juge pas.
    """
    rc, output = await ws_exec(
        login,
        ws_id,
        _tmux("list-panes -a -F '#{session_activity} #{pane_current_command}' 2>/dev/null"),
    )
    if rc in NO_TMUX_SERVER_RCS:
        return "idle", None
    if rc != 0:
        return "unreachable", None
    last: datetime | None = None
    for line in output.strip().splitlines():
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        ts = datetime.fromtimestamp(int(parts[0]), tz=UTC)
        last = ts if last is None or ts > last else last
        cmd = parts[1].strip() if len(parts) > 1 else ""
        if cmd and cmd not in _IDLE_SHELLS:
            return "active", None
    return "idle", last


async def run_idle_pass(
    *,
    conn: AsyncConnection | None = None,
    probe_fn: ProbeFn = probe_workspace_idle,
    threshold_h: float | None = None,
    now: datetime | None = None,
) -> None:
    """Une passe : sonde les workspaces running non épinglés, tient les périodes
    d'inactivité, émet l'alerte au franchissement du seuil (une fois par période).

    Comme la sonde de vivacité : lecture DB → sondes réseau SANS connexion tenue
    → écritures DB. `conn` explicite : tests uniquement.
    """
    if threshold_h is None:
        threshold_h = get_settings().workspace_idle_threshold_h
    if threshold_h <= 0:
        return
    if now is None:
        now = datetime.now(UTC)

    if conn is not None:
        refs, status_rows, prev = await _read_state(conn)
    else:
        from ..db.engine import _get_engine

        async with _get_engine().connect() as read_conn:
            refs, status_rows, prev = await _read_state(read_conn)

    status_map = {r["ws_id"]: r for r in status_rows if r.get("ws_id")}
    running: list[tuple[str, str]] = []  # (ws_id, login), non épinglés
    exempt: list[str] = []  # période terminée : pin, stop, disparu
    for ref in refs:
        ws_id = f"{ref['login']}-{ref['name']}"
        is_running = (status_map.get(ws_id) or {}).get("status") == "running"
        if is_running and not ref.get("keep_active"):
            running.append((ws_id, ref["login"]))
        elif ws_id in prev:
            exempt.append(ws_id)
    # Workspaces supprimés : leur ligne idle ne doit pas survivre.
    known = {f"{r['login']}-{r['name']}" for r in refs}
    exempt.extend(ws_id for ws_id in prev if ws_id not in known)

    results = await asyncio.gather(
        *[probe_fn(login, ws_id) for ws_id, login in running]
    )

    if conn is not None:
        await _apply(conn, running, results, prev, exempt, threshold_h, now)
    else:
        from ..db.engine import _get_engine

        async with _get_engine().begin() as write_conn:
            await _apply(write_conn, running, results, prev, exempt, threshold_h, now)


async def _read_state(
    conn: AsyncConnection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = await list_workspace_refs(None, conn)
    status_rows = await list_all_status_db(conn)
    prev = await workspace_idle_db.get_all(conn)
    return refs, status_rows, prev


async def _apply(
    conn: AsyncConnection,
    running: list[tuple[str, str]],
    results: list[tuple[IdleVerdict, datetime | None]],
    prev: dict[str, dict[str, Any]],
    exempt: list[str],
    threshold_h: float,
    now: datetime,
) -> None:
    to_clear = list(exempt)
    threshold = timedelta(hours=threshold_h)

    for (ws_id, login), (verdict, last_activity) in zip(running, results, strict=True):
        row = prev.get(ws_id)
        if verdict in ("active", "unreachable"):
            if row is not None:
                to_clear.append(ws_id)
            continue

        # Début de période : la dernière activité tmux si connue (plus honnête
        # qu'« aujourd'hui »), sinon la première observation.
        idle_since = last_activity or now
        reset_alert = False
        if row is not None:
            if last_activity is not None and last_activity > row["idle_since"]:
                # Activité reprise entre deux passes → nouvelle période, réarmée.
                idle_since = last_activity
                reset_alert = True
            else:
                idle_since = row["idle_since"]
        await workspace_idle_db.upsert_idle(
            conn, ws_id, login, idle_since, last_activity, now, reset_alert=reset_alert
        )

        already_alerted = (
            row is not None and row.get("alerted_at") is not None and not reset_alert
        )
        if now - idle_since >= threshold and not already_alerted:
            await workspace_idle_db.mark_alerted(conn, ws_id, now)
            _log.warning(
                "workspace_idle_detected",
                ws_id=ws_id,
                login=login,
                idle_since=idle_since.isoformat(),
                idle_hours=round((now - idle_since).total_seconds() / 3600, 1),
            )

    await workspace_idle_db.clear(conn, to_clear)


async def idle_suggestions_loop() -> None:
    """Boucle de fond : une passe toutes les workspace_idle_interval_s."""
    interval = get_settings().workspace_idle_interval_s
    while True:
        try:
            await run_idle_pass()
        except Exception as exc:  # noqa: BLE001 — une boucle de fond ne doit jamais mourir
            _log.exception("workspace_idle_pass_failed", error=str(exc))
        await asyncio.sleep(interval)
