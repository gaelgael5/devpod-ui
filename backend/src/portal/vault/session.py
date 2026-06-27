from __future__ import annotations

_sessions: dict[str, bytes] = {}


def set_master_key(session_id: str, master_key: bytes) -> None:
    _sessions[session_id] = master_key


def get_master_key(session_id: str) -> bytes | None:
    return _sessions.get(session_id)


def is_unlocked(session_id: str) -> bool:
    return session_id in _sessions


def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
