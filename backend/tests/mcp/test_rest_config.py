"""Tranche 3 — déclaration admin des outils d'un backend `rest`.

Tests purs (sans DB) : validation du modèle de déclaration et construction de la
définition catalogue, avec round-trip vers RestToolSpec (garantit que ce qui est
stocké est re-lisible au dispatch).
"""

from __future__ import annotations

import pytest

from portal.mcp.models import RestToolDeclaration, RestToolsSet
from portal.mcp.rest_adapter import RestToolSpec
from portal.mcp.rest_config import build_rest_definition


def _decl(**over: object) -> RestToolDeclaration:
    base: dict[str, object] = {
        "name": "search",
        "description": "recherche RAG",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "spec": {
            "method": "POST",
            "path": "/mcp",
            "body_args": ["query"],
            "secret_field": "api_key",
            "secret_in": "body",
        },
    }
    base.update(over)
    return RestToolDeclaration.model_validate(base)


class TestRestToolDeclaration:
    def test_input_schema_alias(self) -> None:
        decl = _decl()
        assert decl.input_schema["type"] == "object"
        assert isinstance(decl.spec, RestToolSpec)

    def test_default_input_schema(self) -> None:
        decl = RestToolDeclaration.model_validate({"name": "x", "spec": {}})
        assert decl.input_schema == {"type": "object"}

    def test_name_rejects_double_underscore(self) -> None:
        with pytest.raises(ValueError):
            _decl(name="ns__tool")

    def test_name_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError):
            _decl(name="Search")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            _decl(nope=1)

    def test_set_extra_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            RestToolsSet.model_validate({"tools": [], "nope": 1})


class TestBuildRestDefinition:
    def test_definition_shape_and_roundtrip(self) -> None:
        definition = build_rest_definition(_decl())
        assert set(definition) == {"description", "inputSchema", "rest"}
        assert definition["description"] == "recherche RAG"
        # Le mapping stocké est re-validable en RestToolSpec (contrat du dispatch).
        spec = RestToolSpec.model_validate(definition["rest"])
        assert spec.method == "POST"
        assert spec.secret_field == "api_key"
        assert spec.body_args == ["query"]
