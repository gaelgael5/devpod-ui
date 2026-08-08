"""Routes automates : validations (modèles + helpers). Sans DB (tournent en local).

Le flux CRUD complet est couvert par les tests repos (tests/db/test_automation.py,
DB réelle) ; ici on verrouille la validation d'entrée des routes.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from portal.routes.automations import (
    AutomationCreate,
    HeaderIn,
    InjectIn,
    _headers_payload,
    _validate,
)


def test_automation_create_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        AutomationCreate(
            label="x",
            event_types=["test_server.updated"],
            contract_ref="c",
            operation_id="op",
            url="https://x",
            http_method="PUT",
            unknown="oops",
        )


def test_automation_create_defaults() -> None:
    a = AutomationCreate(
        label="x",
        event_types=["test_server.updated"],
        contract_ref="c",
        operation_id="op",
        url="https://x",
        http_method="PUT",
    )
    assert a.scopes == ["*"]
    assert a.active is False
    assert a.stop_chain is False
    assert a.delay_minutes == 0


def test_validate_rejects_unknown_event_type() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate(["nope.event"], "PUT", ["*"])
    assert exc.value.status_code == 422


def test_validate_rejects_bad_method() -> None:
    with pytest.raises(HTTPException):
        _validate(["test_server.updated"], "FETCH", ["*"])


def test_validate_rejects_empty_scopes() -> None:
    with pytest.raises(HTTPException):
        _validate(["test_server.updated"], "PUT", [])


def test_validate_accepts_valid() -> None:
    _validate(["test_server.updated", "workspace.updated"], "put", ["*", "proj"])


def test_headers_payload_requires_value_xor_secret() -> None:
    with pytest.raises(HTTPException):
        _headers_payload([HeaderIn(name="A")])  # ni value ni secret
    with pytest.raises(HTTPException):
        _headers_payload([HeaderIn(name="A", value="v", secret_ref="${vault://x}")])  # les deux


def test_headers_payload_accepts_xor() -> None:
    out = _headers_payload(
        [HeaderIn(name="A", value="v"), HeaderIn(name="B", secret_ref="${vault://x}")]
    )
    assert out == [
        {"name": "A", "value": "v", "secret_ref": None},
        {"name": "B", "value": None, "secret_ref": "${vault://x}"},
    ]


def test_inject_kind_literal() -> None:
    assert InjectIn(kind="host").kind == "host"
    with pytest.raises(ValidationError):
        InjectIn(kind="banana")
