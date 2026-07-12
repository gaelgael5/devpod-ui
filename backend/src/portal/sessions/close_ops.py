"""Fermeture d'une session depuis la page centralisée « Sessions ».

Deux effets, selon la famille :
- **toutes familles** : détache le pont vivant (registre) — le closer annule le
  websocket↔ssh, le process est tué côté handler ;
- **workspace** : tue **en plus** la session tmux sous-jacente (décision produit :
  le bouton « fermer » de /sessions est destructif pour un workspace, il ne se
  contente pas de détacher).
"""

from __future__ import annotations

import shlex

import structlog
from fastapi import HTTPException

from ..devpod.exec import tmux as _tmux
from ..devpod.exec import ws_exec
from ..events.bus import emit_event

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
    _log.info("session_closed_via_sessions", ws_id=ws_id, session=session_name, actor=actor)
    await emit_event(
        "session.closed", actor=actor, workspace=name, subject={"session": session_name}
    )
