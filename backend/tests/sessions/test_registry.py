from __future__ import annotations

import pytest

from portal.sessions import registry
from portal.sessions.registry import LiveTerminal


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    registry.clear()
    yield
    registry.clear()


def _term(id: str, owner: str, family: registry.Family, target: str, session=None):
    return LiveTerminal(
        id=id, family=family, target=target, owner=owner, session=session, since=1.0
    )


def test_register_and_list_all() -> None:
    t1 = _term("a", "alice", "workspace", "alice-ws", "main")
    t2 = _term("b", "bob", "host", "node1")
    registry.register(t1)
    registry.register(t2)
    assert {t.id for t in registry.list_all()} == {"a", "b"}


def test_register_idempotent_by_id() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws", "main"))
    registry.register(_term("a", "alice", "workspace", "alice-ws", "other"))
    all_terms = registry.list_all()
    assert len(all_terms) == 1
    assert all_terms[0].session == "other"


def test_unregister_removes_and_is_idempotent() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws"))
    registry.unregister("a")
    registry.unregister("a")  # inconnu → silencieux
    assert registry.list_all() == []


def test_list_for_owner_filters() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws"))
    registry.register(_term("b", "bob", "workspace", "bob-ws"))
    assert {t.id for t in registry.list_for_owner("alice")} == {"a"}


def test_attached_index_all() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws", "main"))
    registry.register(_term("b", "bob", "host", "node1"))
    idx = registry.attached_index(owner=None)
    assert ("workspace", "alice-ws", "main") in idx
    assert ("host", "node1", None) in idx


def test_attached_index_scoped_to_owner() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws", "main"))
    registry.register(_term("b", "bob", "workspace", "bob-ws", "main"))
    idx = registry.attached_index(owner="alice")
    assert idx == {("workspace", "alice-ws", "main")}


def test_new_terminal_generates_stable_id_and_since() -> None:
    t = registry.new_terminal("workspace", "alice-ws", "alice", "main")
    assert t.id and len(t.id) == 32  # uuid4 hex
    assert t.since > 0
    assert (t.family, t.target, t.session) == ("workspace", "alice-ws", "main")


def test_live_terminal_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    t = _term("a", "alice", "workspace", "alice-ws")
    with pytest.raises(FrozenInstanceError):
        t.owner = "mallory"  # type: ignore[misc]


# ── close_matching ──────────────────────────────────────────────────────────


def test_close_matching_invokes_closer_and_counts() -> None:
    called: list[str] = []
    registry.register(
        _term("a", "alice", "test", "node-vm"), closer=lambda: called.append("a")
    )
    n = registry.close_matching(family="test", target="node-vm", session=None, owner="alice")
    assert n == 1
    assert called == ["a"]


def test_close_matching_scoped_to_owner_ignores_others() -> None:
    called: list[str] = []
    registry.register(_term("a", "alice", "test", "node-vm"), closer=lambda: called.append("a"))
    registry.register(_term("b", "bob", "test", "node-vm"), closer=lambda: called.append("b"))
    n = registry.close_matching(family="test", target="node-vm", session=None, owner="alice")
    assert n == 1
    assert called == ["a"]


def test_close_matching_admin_owner_none_closes_all_matching() -> None:
    called: list[str] = []
    registry.register(_term("a", "alice", "host", "node1"), closer=lambda: called.append("a"))
    registry.register(_term("b", "bob", "host", "node1"), closer=lambda: called.append("b"))
    n = registry.close_matching(family="host", target="node1", session=None, owner=None)
    assert n == 2
    assert sorted(called) == ["a", "b"]


def test_close_matching_no_match_returns_zero() -> None:
    registry.register(_term("a", "alice", "workspace", "alice-ws", "main"), closer=lambda: None)
    n = registry.close_matching(
        family="workspace", target="alice-ws", session="other", owner="alice"
    )
    assert n == 0


def test_close_matching_terminal_without_closer_not_counted() -> None:
    registry.register(_term("a", "alice", "host", "node1"))  # pas de closer
    n = registry.close_matching(family="host", target="node1", session=None, owner=None)
    assert n == 0
