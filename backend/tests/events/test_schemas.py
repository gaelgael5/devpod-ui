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
        "workspace.created": {"actor": "a", "workspace": "p", "ws_id": "a-p", "node": "n"},
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
