"""Tests for GET /api/compose/nodes helper and route."""

from types import SimpleNamespace

from portal.routes import compose as r


def test_eligible_hosts_keeps_ssh_only() -> None:
    hosts = [
        SimpleNamespace(name="n1", type="ssh", usage="workspaces"),
        SimpleNamespace(name="tls", type="docker-tls", usage="workspaces"),
        SimpleNamespace(name="n2", type="ssh", usage="tests"),
    ]
    assert [h.name for h in r._eligible_hosts(hosts)] == ["n1", "n2"]


def test_eligible_hosts_excludes_autres() -> None:
    """usage='autres' = inventaire simple : jamais une cible de déploiement compose."""
    hosts = [
        SimpleNamespace(name="n1", type="ssh", usage="workspaces"),
        SimpleNamespace(name="inv", type="ssh", usage="autres"),
    ]
    assert [h.name for h in r._eligible_hosts(hosts)] == ["n1"]
