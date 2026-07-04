from __future__ import annotations

import time

# Aligné sur max_age du cookie de session (app.py, _PortalSessionMiddleware) :
# une master key déchiffrée ne doit jamais survivre en RAM plus longtemps que le
# cookie qui l'a déverrouillée, même si l'utilisateur ne se déconnecte jamais
# explicitement (bug 030).
_SESSION_TTL_S = 86400

_sessions: dict[str, tuple[bytes, float]] = {}


def _sweep_expired(now: float) -> None:
    expired = [sid for sid, (_, expires_at) in _sessions.items() if now >= expires_at]
    for sid in expired:
        del _sessions[sid]


def set_master_key(session_id: str, master_key: bytes) -> None:
    now = time.monotonic()
    _sweep_expired(now)  # borne la mémoire : purge les sessions abandonnées à chaque unlock
    _sessions[session_id] = (master_key, now + _SESSION_TTL_S)


def get_master_key(session_id: str) -> bytes | None:
    entry = _sessions.get(session_id)
    if entry is None:
        return None
    master_key, expires_at = entry
    if time.monotonic() >= expires_at:
        _sessions.pop(session_id, None)
        return None
    return master_key


def is_unlocked(session_id: str) -> bool:
    return get_master_key(session_id) is not None


def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
