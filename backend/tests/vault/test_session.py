from __future__ import annotations

import portal.vault.session as session_mod
from portal.vault.session import clear_session, get_master_key, is_unlocked, set_master_key


def test_set_and_get():
    set_master_key("s1", b"x" * 32)
    assert get_master_key("s1") == b"x" * 32
    clear_session("s1")


def test_unknown_returns_none():
    assert get_master_key("ghost") is None


def test_is_unlocked():
    set_master_key("s2", b"y" * 32)
    assert is_unlocked("s2") is True
    clear_session("s2")
    assert is_unlocked("s2") is False


def test_clear_removes():
    set_master_key("s3", b"z" * 32)
    clear_session("s3")
    assert get_master_key("s3") is None


def test_overwrite():
    set_master_key("s4", b"a" * 32)
    set_master_key("s4", b"b" * 32)
    assert get_master_key("s4") == b"b" * 32
    clear_session("s4")


# ---------------------------------------------------------------------------
# Bug 030 : TTL aligné sur max_age du cookie — une master key ne doit jamais
# survivre indéfiniment en RAM au-delà de l'expiration de la session.
# ---------------------------------------------------------------------------


def test_get_master_key_expires_after_ttl(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(session_mod.time, "monotonic", lambda: t[0])

    set_master_key("s5", b"k" * 32)
    assert get_master_key("s5") == b"k" * 32

    t[0] += session_mod._SESSION_TTL_S + 1  # au-delà du TTL
    assert get_master_key("s5") is None


def test_is_unlocked_false_after_ttl(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(session_mod.time, "monotonic", lambda: t[0])

    set_master_key("s6", b"k" * 32)
    assert is_unlocked("s6") is True

    t[0] += session_mod._SESSION_TTL_S + 1
    assert is_unlocked("s6") is False


def test_expired_session_evicted_from_dict_not_just_hidden(monkeypatch):
    """Une session expirée doit être retirée du dict (fuite mémoire, bug 030),
    pas seulement masquée par le contrôle de lecture."""
    t = [1000.0]
    monkeypatch.setattr(session_mod.time, "monotonic", lambda: t[0])

    set_master_key("s7", b"k" * 32)
    t[0] += session_mod._SESSION_TTL_S + 1
    get_master_key("s7")  # déclenche l'éviction paresseuse

    assert "s7" not in session_mod._sessions


def test_set_master_key_sweeps_other_expired_sessions(monkeypatch):
    """Un nouvel unlock balaie les sessions abandonnées expirées (bornage mémoire),
    pas seulement celle qu'on est en train de créer."""
    t = [1000.0]
    monkeypatch.setattr(session_mod.time, "monotonic", lambda: t[0])

    set_master_key("abandoned", b"k" * 32)
    t[0] += session_mod._SESSION_TTL_S + 1  # "abandoned" expire, jamais relue

    set_master_key("fresh", b"k" * 32)  # nouvel unlock : balaie au passage

    assert "abandoned" not in session_mod._sessions
    assert get_master_key("fresh") == b"k" * 32
    clear_session("fresh")
