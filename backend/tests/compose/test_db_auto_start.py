"""Tests DB layer de la préférence auto-start (pur, sans TestClient)."""
from portal.compose import db


def test_row_to_auto_start() -> None:
    row = {
        "id": 1, "owner_login": "alice", "template_id": "alloy-collector",
        "env_values": {"WEB_PORT": "3000"}, "created_at": None,
    }
    entry = db._row_to_auto_start(row)
    assert entry.id == 1
    assert entry.owner_login == "alice"
    assert entry.template_id == "alloy-collector"
    assert entry.env_values == {"WEB_PORT": "3000"}


def test_row_to_auto_start_defaults_empty_env_values() -> None:
    row = {
        "id": 2, "owner_login": "bob", "template_id": "searxng",
        "env_values": None, "created_at": None,
    }
    entry = db._row_to_auto_start(row)
    assert entry.env_values == {}
