"""Logique pure du runner : matching (type + portée), dedup_key, contexte, template."""

from __future__ import annotations

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
        "scopes": ["*"],
        "delay_minutes": 0,
        "stop_chain": False,
    }
    base.update(over)
    return base


def test_matches_type_and_wildcard_scope() -> None:
    assert r.matches(_auto(), _event()) is True


def test_matches_scope_by_workspace() -> None:
    assert r.matches(_auto(scopes=["proj"]), _event(workspace="proj")) is True
    assert r.matches(_auto(scopes=["other"]), _event(workspace="proj")) is False


def test_no_match_on_type() -> None:
    assert r.matches(_auto(event_types=["session.created"]), _event()) is False


def test_dedup_key_prefers_natural_then_seq() -> None:
    assert r.dedup_key(_event(dedup_key="host:h1")) == "host:h1"
    assert r.dedup_key(_event(dedup_key=None, seq=42)) == "seq:42"


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
