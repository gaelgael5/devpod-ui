"""Tests for GET /api/compose/nodes helper and route."""
from types import SimpleNamespace

from portal.routes import compose as r


def test_eligible_nodes_filters_ssh() -> None:
    hosts = [
        SimpleNamespace(name="n1", type="ssh"),
        SimpleNamespace(name="tls", type="docker-tls"),
        SimpleNamespace(name="n2", type="ssh"),
    ]
    rows = r._eligible_nodes(hosts)
    assert rows == [{"node_id": "n1", "name": "n1"}, {"node_id": "n2", "name": "n2"}]
