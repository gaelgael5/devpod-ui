"""Catalogue de découverte + dataSchemas des events produits."""

from __future__ import annotations

import jsonschema
import pytest

from portal.events import schemas
from portal.events.models import EVENT_TYPES


def test_every_event_type_has_a_dataschema() -> None:
    for t in EVENT_TYPES:
        assert schemas.event_code_for(t) in schemas.DATA_SCHEMA_BY_CODE


def test_catalog_shape() -> None:
    cat = schemas.catalog()
    assert cat["specVersion"] == "1.0"
    assert cat["revision"].startswith("sha256:")
    codes = {e["eventCode"] for e in cat["events"]}
    assert codes == set(schemas.DATA_SCHEMA_BY_CODE)
    assert len(cat["events"]) == len(EVENT_TYPES)


def test_schema_version_lookup_and_404() -> None:
    code = schemas.event_code_for("workspace.created")
    payload = schemas.schema_version(code, 1)
    assert payload is not None
    assert payload["eventCode"] == code
    assert payload["version"] == 1
    assert payload["hash"].startswith("sha256:")
    # version inconnue / code inconnu → None (→ 404 côté route)
    assert schemas.schema_version(code, 2) is None
    assert schemas.schema_version("nope.x.v1", 1) is None
    assert schemas.schema_versions(code) == [1]
    assert schemas.schema_versions("nope") is None


def test_dataschemas_are_valid_json_schema() -> None:
    for sch in schemas.DATA_SCHEMA_BY_CODE.values():
        jsonschema.Draft202012Validator.check_schema(sch)


def test_representative_payload_conforms_like_workflow() -> None:
    # Le workflow valide les champs métier contre le dataSchema — on vérifie qu'un
    # payload représentatif de chaque event passe sa propre validation.
    samples: dict[str, dict[str, object]] = {
        "user.created": {"actor": "gael", "login": "gael", "sub": "kc-123", "email": "g@x.org"},
        "user.refreshed": {"actor": "gael", "login": "gael", "sub": "kc-123", "email": ""},
        "user.connected": {"actor": "gael", "login": "gael", "sub": "kc-123", "email": "g@x.org"},
        "user.disconnected": {"actor": "gael", "login": "gael", "sub": "kc-123"},
        "user.deleted": {"actor": "admin", "login": "gael", "sub": "kc-123"},
        "user.paused": {"actor": "admin", "login": "gael", "sub": "kc-123"},
        "user.resumed": {"actor": "admin", "login": "gael", "sub": "kc-123"},
        "workspace.created": {"actor": "a", "workspace": "p", "ws_id": "a-p", "node": "n"},
        "workspace.updated": {
            "actor": "a",
            "workspace": "p",
            "ws_id": "a-p",
            "node": "n",
            "address": None,
            "status": "running",
        },
        "workspace.deleted": {
            "actor": "a",
            "workspace": "p",
            "ws_id": "a-p",
            "recovery_branch": None,
        },
        "session.created": {"actor": "a", "workspace": "p", "session": "s"},
        "compose_service.started": {
            "actor": "a",
            "deployment_uid": "u",
            "deployment_id": "d",
            "template_id": "t",
            "node_id": "n",
            "action": "up",
        },
        "test_server.created": {
            "actor": "a",
            "workspace": "p",
            "host_name": "h",
            "alias": "al",
            "address": "1.2.3.4",
            "hypervisor": "pve",
        },
        "test_server.updated": {
            "actor": "a",
            "workspace": "p",
            "host_name": "h",
            "alias": "al",
            "address": "root@1.2.3.4",
            "password_changed": True,
        },
    }
    for event_type, payload in samples.items():
        sch = schemas.DATA_SCHEMA_BY_CODE[schemas.event_code_for(event_type)]
        jsonschema.Draft202012Validator(sch).validate(payload)


def test_revision_changes_when_a_schema_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    before = schemas.catalog()["revision"]
    code = schemas.event_code_for("workspace.stopped")
    mutated = {**schemas.DATA_SCHEMA_BY_CODE[code], "title": "changed"}
    monkeypatch.setitem(schemas.DATA_SCHEMA_BY_CODE, code, mutated)
    assert schemas.catalog()["revision"] != before


def test_variables_for_is_event_prefixed_and_contextual() -> None:
    user_vars = schemas.variables_for("user.created")
    assert user_vars[0] == "event.type"
    assert "event.actor" in user_vars
    assert "event.sub" in user_vars and "event.identity" in user_vars
    assert "event.workspace" not in user_vars  # user.created n'a pas de workspace
    ws_vars = schemas.variables_for("workspace.created")
    assert "event.workspace" in ws_vars  # contextuel : présent ici


def test_variables_by_type_covers_registry() -> None:
    assert set(schemas.variables_by_type()) == set(EVENT_TYPES)


def test_workspace_events_carry_owner_identity() -> None:
    # Enrichissement identité propriétaire (sub = clé de matching Termix).
    for t in ("workspace.created", "workspace.restarted", "workspace.stopped", "workspace.deleted"):
        v = schemas.variables_for(t)
        assert {"event.login", "event.sub", "event.email", "event.identity"} <= set(v), t
