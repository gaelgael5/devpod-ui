"""Émetteur de diff sur la sonde tmux : détecte les sessions créées/tuées **hors
du portail** et émet `session.created` / `session.closed` en conséquence.

Best-effort, non transactionnel (option de la tranche T1 de l'epic Termix). Deux
garde-fous contre les faux positifs / doublons :

- **Seed silencieux** : la première sonde joignable d'un workspace adopte l'état
  courant comme référence, sans rien émettre (les sessions déjà là relèvent du
  backfill, pas d'un « created »).
- **Coordination avec le portail** : les mutations de session du portail appellent
  `note_session_created` / `note_session_closed`, qui tiennent l'état « sessions
  connues » à jour. La sonde ne compare donc que l'écart entre le tmux réel et ce
  que le portail sait déjà — un `session.created`/`closed` déclenché par le portail
  n'est jamais ré-émis par la sonde.

N'émet **que sur une sonde joignable** (`rc == 0`) : une injoignabilité passagère
ne doit jamais produire de faux `session.closed`.
"""

from __future__ import annotations

import asyncio

import structlog

from .aggregate import probe_workspace_sessions

_log = structlog.get_logger(__name__)

# Intervalle du balayage. Volontairement lâche : la sonde par workspace est déjà
# cachée (TTL 4 s) et sérialisée — un tick lent ne martèle pas les hosts.
_DEFAULT_INTERVAL_S = 60.0

# ws_id ayant établi leur référence (première sonde jointe). Distinct de _known :
# tant qu'un workspace n'est pas seedé, aucune émission (adoption silencieuse).
_seeded: set[str] = set()
# ws_id -> ensemble des sessions connues (sondes + notifications du portail).
_known: dict[str, set[str]] = {}


def compute_session_diff(previous: set[str], current: set[str]) -> tuple[list[str], list[str]]:
    """(apparues, disparues) triées entre deux observations d'un workspace."""
    return sorted(current - previous), sorted(previous - current)


def note_session_created(ws_id: str, session: str) -> None:
    """Le portail vient de créer `session` : la marquer connue (anti-doublon sonde)."""
    _known.setdefault(ws_id, set()).add(session)


def note_session_closed(ws_id: str, session: str) -> None:
    """Le portail vient de fermer `session` : la retirer du connu (anti-doublon sonde)."""
    known = _known.get(ws_id)
    if known is not None:
        known.discard(session)


def reset_state() -> None:
    """Oublie tout l'état mémorisé (tests / arrêt propre)."""
    _seeded.clear()
    _known.clear()


async def _reconcile_workspace(login: str, ws_id: str) -> tuple[int, int]:
    """Sonde un workspace et émet les diffs hors-portail. Retourne (créées, fermées)."""
    from ..events.bus import emit_event

    rc, sessions = await probe_workspace_sessions(login, ws_id)
    if rc != 0:
        return (0, 0)  # injoignable : on ne conclut rien
    current = set(sessions)
    if ws_id not in _seeded:
        _seeded.add(ws_id)
        _known[ws_id] = current
        return (0, 0)  # seed silencieux
    appeared, disappeared = compute_session_diff(_known.get(ws_id, set()), current)
    _known[ws_id] = current
    ws_name = ws_id.removeprefix(f"{login}-")
    for s in appeared:
        await emit_event(
            "session.created",
            actor="system",
            workspace=ws_name,
            subject={"session": s, "start_recipe": None},
            dedup_key=f"probe:{ws_id}:{s}:created",
        )
    for s in disappeared:
        await emit_event(
            "session.closed",
            actor="system",
            workspace=ws_name,
            subject={"session": s},
            dedup_key=f"probe:{ws_id}:{s}:closed",
        )
    return (len(appeared), len(disappeared))


async def probe_once() -> dict[str, int]:
    """Un passage : sonde chaque workspace running, émet les diffs. Best-effort.

    Sérialisé (pas de rafale de sondes concurrentes). Un échec sur un workspace
    n'interrompt pas le balayage. Purge l'état des workspaces qui ne tournent plus.
    """
    from ..db.engine import _get_engine
    from ..db.workspace_status import list_running_db

    async with _get_engine().connect() as conn:
        running = await list_running_db(conn)

    seen: set[str] = set()
    created = closed = 0
    for row in running:
        login = row.get("login") or ""
        ws_id = row.get("ws_id") or ""
        if not login or not ws_id:
            continue
        seen.add(ws_id)
        try:
            a, d = await _reconcile_workspace(login, ws_id)
            created += a
            closed += d
        except Exception:
            _log.warning("session_diff_probe_ws_failed", ws_id=ws_id, exc_info=True)

    # Oublie les workspaces disparus : évite une fuite mémoire et un faux « created »
    # en masse si le workspace revient (il sera re-seedé silencieusement).
    for gone in _seeded - seen:
        _seeded.discard(gone)
        _known.pop(gone, None)
    return {"created": created, "closed": closed}


async def diff_probe_loop(interval_s: float = _DEFAULT_INTERVAL_S) -> None:
    """Boucle de fond : émet les diffs de sonde hors-portail à intervalle lâche."""
    await asyncio.sleep(5)  # laisse le portail démarrer
    while True:
        try:
            counts = await probe_once()
            if counts["created"] or counts["closed"]:
                _log.info("session_diff_probe_swept", **counts)
        except Exception:
            _log.warning("session_diff_probe_loop_failed", exc_info=True)
        await asyncio.sleep(interval_s)
