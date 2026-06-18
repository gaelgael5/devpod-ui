from __future__ import annotations

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
