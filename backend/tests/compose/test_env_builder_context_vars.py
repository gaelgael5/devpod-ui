"""Tests de render_env_file avec context_vars (spec 30 §3.2)."""

from __future__ import annotations

from portal.compose.env_builder import render_env_file


def test_render_without_context_vars() -> None:
    result = render_env_file({"FOO": "bar"})
    assert 'FOO="bar"' in result


def test_context_vars_appended() -> None:
    result = render_env_file(
        {"FOO": "user_val"},
        context_vars={"LOKI_URL": "http://loki:3100", "ROLE": "workspace"},
    )
    assert 'FOO="user_val"' in result
    assert 'LOKI_URL="http://loki:3100"' in result
    assert 'ROLE="workspace"' in result


def test_context_vars_override_user_value() -> None:
    result = render_env_file(
        {"LOKI_URL": "user_override"},
        context_vars={"LOKI_URL": "http://portal:3100"},
    )
    assert 'LOKI_URL="http://portal:3100"' in result
    assert "user_override" not in result


def test_none_context_vars_ignored() -> None:
    result = render_env_file({"FOO": "bar"}, context_vars=None)
    assert 'FOO="bar"' in result
