from __future__ import annotations

import structlog.testing

from portal.secrets.types import Secret


def test_reveal_returns_value():
    assert Secret("hunter2").reveal() == "hunter2"


def test_repr_masks_value():
    assert repr(Secret("hunter2")) == "Secret(***)"
    assert "hunter2" not in repr(Secret("hunter2"))


def test_str_masks_value():
    assert str(Secret("hunter2")) == "***"
    assert "hunter2" not in str(Secret("hunter2"))


def test_f_string_does_not_leak():
    s = Secret("hunter2")
    assert "hunter2" not in f"secret={s}"


def test_format_does_not_leak():
    s = Secret("hunter2")
    assert "hunter2" not in "secret={}".format(s)  # noqa: UP032


def test_equality():
    assert Secret("abc") == Secret("abc")
    assert Secret("abc") != Secret("xyz")


def test_does_not_leak_in_structlog():
    s = Secret("verysecretvalue")
    with structlog.testing.capture_logs() as cap:
        structlog.get_logger().info("processing", secret=s)
    for event in cap:
        for v in event.values():
            assert "verysecretvalue" not in str(v)
