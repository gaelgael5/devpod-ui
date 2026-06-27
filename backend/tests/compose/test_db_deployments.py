"""Tests DB layer de déploiements (spec 26, task 5)."""
from portal.compose import db


def test_row_to_deployment() -> None:
    row = {
        "id": "d1", "template_id": "t", "template_version": "1", "node_id": "n",
        "owner_login": "alice", "env_values": {"A": "${vault://x/y}"}, "host_ports": [3000],
        "status": "running", "last_error": None, "created_at": None, "updated_at": None,
    }
    dep = db._row_to_deployment(row)
    assert dep.id == "d1" and dep.host_ports == [3000]
    assert dep.env_values == {"A": "${vault://x/y}"}
