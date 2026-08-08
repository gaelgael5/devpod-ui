"""Contrats OpenAPI : parsing (JSON/YAML), version, énumération, résolution."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from portal.automations import contracts as c

_SPEC = {
    "openapi": "3.0.0",
    "info": {"version": "2.1.0"},
    "servers": [{"url": "https://termix.example.org/api/"}],
    "paths": {
        "/hosts/{id}": {
            "put": {"operationId": "putHost", "summary": "Upsert host"},
            "delete": {"summary": "Delete host"},
        },
        "/hosts": {"get": {"operationId": "listHosts"}},
    },
}


def test_parse_spec_json() -> None:
    assert c.parse_spec(json.dumps(_SPEC))["info"]["version"] == "2.1.0"


def test_parse_spec_yaml() -> None:
    raw = "openapi: 3.0.0\ninfo:\n  version: '9'\npaths: {}\n"
    assert c.parse_spec(raw)["info"]["version"] == "9"


def test_parse_spec_invalid() -> None:
    with pytest.raises(HTTPException):
        c.parse_spec("{not json and : not yaml: [")
    with pytest.raises(HTTPException):
        c.parse_spec(json.dumps({"openapi": "3.0.0"}))  # pas de 'paths'


def test_extract_version() -> None:
    assert c.extract_version(_SPEC) == "2.1.0"
    assert c.extract_version({"paths": {}}) == ""


def test_list_operations_covers_all_verbs_and_synthesises_id() -> None:
    ops = c.list_operations(_SPEC)
    ids = {o["operation_id"] for o in ops}
    assert "putHost" in ids
    assert "listHosts" in ids
    assert "delete /hosts/{id}" in ids  # operationId absent → id déterministe


def test_resolve_operation_builds_url_from_servers() -> None:
    resolved = c.resolve_operation(_SPEC, "putHost")
    assert resolved is not None
    assert resolved["method"] == "PUT"
    assert resolved["url"] == "https://termix.example.org/api/hosts/{id}"


def test_resolve_operation_unknown() -> None:
    assert c.resolve_operation(_SPEC, "nope") is None
