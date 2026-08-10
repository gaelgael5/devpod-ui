"""Logique pure du runner : matching (type + portée), dedup_key, contexte, template."""

from __future__ import annotations

import pytest

from portal.automations import runner as r


def _event(**over: object) -> dict:
    base = {
        "seq": 5,
        "event_type": "test_server.updated",
        "actor": "alice",
        "workspace": "proj",
        "subject": {"host_name": "h1", "address": "root@1.2.3.4", "password_changed": True},
        "dedup_key": None,
    }
    base.update(over)
    return base


def _auto(**over: object) -> dict:
    base = {
        "event_types": ["test_server.updated"],
        "delay_minutes": 0,
        "stop_chain": False,
    }
    base.update(over)
    return base


def test_matches_on_type() -> None:
    # Le matching ne dépend QUE du type d'event (plus de filtre par workspace).
    assert r.matches(_auto(), _event()) is True
    assert r.matches(_auto(), _event(workspace="autre")) is True


def test_no_match_on_type() -> None:
    assert r.matches(_auto(event_types=["session.created"]), _event()) is False


def test_dedup_key_prefers_natural_then_seq() -> None:
    assert r.dedup_key(_event(dedup_key="host:h1")) == "host:h1"
    assert r.dedup_key(_event(dedup_key=None, seq=42)) == "seq:42"


def test_build_context_event_namespace() -> None:
    ev = {
        "seq": 1,
        "event_type": "user.created",
        "actor": "alice",
        "subject": {"login": "alice", "sub": "S-1", "email": "a@x.org", "identity": None},
    }
    ctx = r.build_context(ev)
    assert ctx["event.type"] == "user.created"
    assert ctx["event.actor"] == "alice"
    assert ctx["event.login"] == "alice"
    assert ctx["event.sub"] == "S-1"
    assert ctx["event.email"] == "a@x.org"
    assert ctx["event.identity"] == ""  # None → "" (jamais littéral)
    assert ctx["user.sub"] == "S-1"  # alias de compat conservé


def test_build_context_no_user_namespace_for_non_user_event() -> None:
    ctx = r.build_context(_event())  # test_server.updated
    assert "user.sub" not in ctx


def test_build_context_exposes_root_and_subject() -> None:
    ctx = r.build_context(_event())
    assert ctx["actor"] == "alice"
    assert ctx["workspace"] == "proj"
    assert ctx["type"] == "test_server.updated"
    assert ctx["subject.host_name"] == "h1"
    assert ctx["host_name"] == "h1"  # alias plat
    assert ctx["subject.password_changed"] == "True"


def test_render_template_substitutes_known_leaves_unknown() -> None:
    tmpl = '{"name":"{subject.host_name}","addr":"{address}","who":"{actor}","x":"{missing}"}'
    ctx = r.build_context(_event())
    out = r.render_template(tmpl, ctx)
    assert '"name":"h1"' in out
    assert '"addr":"root@1.2.3.4"' in out
    assert '"who":"alice"' in out
    assert '"x":"{missing}"' in out  # inconnu laissé intact


def test_system_ref_regex_matches_slug() -> None:
    m = r._SYSTEM_REF_RE.match("${system://termix-apikey}")
    assert m is not None and m.group(1) == "termix-apikey"
    # Rejette les slugs invalides et les autres schémas.
    assert r._SYSTEM_REF_RE.match("${vault://foo}") is None
    assert r._SYSTEM_REF_RE.match("${system://Bad Slug}") is None


@pytest.mark.asyncio
async def test_run_filter_passes_when_unconfigured() -> None:
    # Sans (operator, filter_url, filter_jsonpath) le gate passe sans appel réseau.
    passed, preview, resp = await r._run_filter(_auto(), {}, client=None)  # type: ignore[arg-type]
    assert passed is True and preview == "" and resp is None


@pytest.mark.asyncio
async def test_resolve_headers_value_prefix_and_flags() -> None:
    headers = [
        {"name": "X-Api-Key", "value": "abc", "secret_ref": None, "value_prefix": ""},
        {"name": "Authorization", "value": "tok", "secret_ref": None, "value_prefix": "Bearer "},
        {"name": "X-Off", "value": "z", "secret_ref": None, "enabled": False},
        {"name": "X-Stub", "value": None, "secret_ref": None},  # auth non configuré
    ]
    out = await r._resolve_headers(headers)
    assert out == {"X-Api-Key": "abc", "Authorization": "Bearer tok"}
