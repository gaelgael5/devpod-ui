"""Fermeture d'une session depuis la page centralisée « Sessions ».

Deux effets, selon la famille :
- **toutes familles** : détache le pont vivant (registre) — le closer annule le
  websocket↔ssh, le process est tué côté handler ;
- **workspace** et **host** : tue **en plus** la session tmux sous-jacente
  (décision produit : le bouton « fermer » de /sessions est destructif, il ne
  se contente pas de détacher).
"""

from __future__ import annotations

import shlex

import structlog
from fastapi import HTTPException

from ..devpod.exec import tmux as _tmux
from ..devpod.exec import ws_exec
from ..devpod.host_exec import run_host_command
from ..events.bus import emit_event
from .aggregate import invalidate_sessions_cache

_log = structlog.get_logger(__name__)


async def kill_tmux_session(*, owner: str, name: str, session_name: str, actor: str) -> None:
    """Tue la session tmux `session_name` du conteneur `<owner>-<name>`.

    `owner` = propriétaire du conteneur (peut différer de `actor` en vue admin) ;
    `actor` = login de l'appelant, tracé dans l'event `session.closed`.
    Les composants (owner/name/session) sont validés par l'appelant avant usage.
    """
    ws_id = f"{owner}-{name}"
    rc, output = await ws_exec(owner, ws_id, _tmux(f"kill-session -t {shlex.quote(session_name)}"))
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"Failed to kill tmux session: {output}")
    invalidate_sessions_cache()
    _log.info("session_closed_via_sessions", ws_id=ws_id, session=session_name, actor=actor)
    await emit_event(
        "session.closed", actor=actor, workspace=name, subject={"session": session_name}
    )


async def kill_host_tmux_session(*, host_name: str, session_name: str, actor: str) -> None:
    """Tue la session tmux `session_name` sur le host admin `host_name`.

    Miroir de `kill_tmux_session` pour la famille `host` (terminaux tmux sur les
    nœuds, socket par défaut de l'utilisateur SSH). Réservé à un appelant admin
    (garanti par la route). Host inconnu → 404 ; échec SSH/tmux → 502.
    """
    from ..config.store import load_global

    host = next((h for h in load_global().hosts if h.name == host_name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {host_name!r} not found")
    try:
        rc, _out, err = await run_host_command(
            host, f"tmux kill-session -t {shlex.quote(session_name)}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to kill host tmux session: {exc}"
        ) from exc
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"Failed to kill host tmux session: {err}")
    invalidate_sessions_cache()
    _log.info("host_session_closed_via_sessions", host=host_name, session=session_name, actor=actor)
    await emit_event(
        "session.closed", actor=actor, subject={"host": host_name, "session": session_name}
    )
