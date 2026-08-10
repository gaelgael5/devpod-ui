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
    ContractUpdate,
    FilterCallIn,
    HeaderIn,
    InjectIn,
    _headers_payload,
    _normalize_slug,
    _resolve_slug,
    _validate,
)


def test_contract_update_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        ContractUpdate(label="x", unknown="oops")


def test_contract_update_defaults_refresh_true() -> None:
    u = ContractUpdate(source_url="https://x/openapi.json")
    assert u.refresh is True
    assert u.label is None


def test_contract_update_allows_partial_rename() -> None:
    u = ContractUpdate(label="Nouveau nom")
    assert u.model_dump(exclude_unset=True) == {"label": "Nouveau nom"}


def test_contract_update_clear_url() -> None:
    u = ContractUpdate(source_url="", refresh=False)
    assert u.model_dump(exclude_unset=True) == {"source_url": "", "refresh": False}


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
    assert a.active is False
    assert a.stop_chain is False
    assert a.delay_minutes == 0


def test_validate_rejects_unknown_event_type() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate(["nope.event"], "PUT")
    assert exc.value.status_code == 422


def test_validate_rejects_bad_method() -> None:
    with pytest.raises(HTTPException):
        _validate(["test_server.updated"], "FETCH")


def test_validate_accepts_valid() -> None:
    _validate(["test_server.updated", "workspace.updated"], "put")


def test_headers_payload_rejects_value_and_secret_together() -> None:
    with pytest.raises(HTTPException):
        _headers_payload([HeaderIn(name="A", value="v", secret_ref="${vault://x}")])


def test_headers_payload_allows_unconfigured_stub() -> None:
    # Ni value ni secret = stub d'auth non configuré : accepté (ignoré à l'appel).
    out = _headers_payload([HeaderIn(name="A", required=True, value_prefix="Bearer ")])
    assert out == [
        {
            "name": "A",
            "value": None,
            "secret_ref": None,
            "value_prefix": "Bearer ",
            "required": True,
            "enabled": True,
        }
    ]


def test_headers_payload_carries_prefix_and_flags() -> None:
    out = _headers_payload(
        [
            HeaderIn(name="A", value="v"),
            HeaderIn(name="B", secret_ref="${system://k}", value_prefix="Bearer ", enabled=False),
        ]
    )
    assert out == [
        {
            "name": "A",
            "value": "v",
            "secret_ref": None,
            "value_prefix": "",
            "required": False,
            "enabled": True,
        },
        {
            "name": "B",
            "value": None,
            "secret_ref": "${system://k}",
            "value_prefix": "Bearer ",
            "required": False,
            "enabled": False,
        },
    ]


def test_inject_kind_literal() -> None:
    assert InjectIn(kind="host").kind == "host"
    with pytest.raises(ValidationError):
        InjectIn(kind="banana")


def test_normalize_slug() -> None:
    assert _normalize_slug("Sync Termix Hosts !") == "sync-termix-hosts"
    assert _normalize_slug("  Déjà__vu  ") == "d-j-vu"  # non-[a-z0-9] → '-'
    assert _normalize_slug("---") == ""


def test_resolve_slug_from_label_when_empty() -> None:
    assert _resolve_slug("", "Sync Termix") == "sync-termix"
    assert _resolve_slug("my-slug", "ignored") == "my-slug"


def test_resolve_slug_rejects_empty_result() -> None:
    with pytest.raises(HTTPException):
        _resolve_slug("", "!!!")  # ni slug ni label normalisable


def test_automation_create_accepts_slug_and_filter() -> None:
    a = AutomationCreate(
        label="L",
        slug="my-auto",
        event_types=["test_server.updated"],
        contract_ref="c",
        operation_id="op",
        url="https://x/y",
        http_method="POST",
        filter_contract_ref="c",
        filter_operation_id="listUsers",
        filter_url="https://x/users/list",
        filter_method="GET",
    )
    assert a.slug == "my-auto" and a.filter_method == "GET"


def test_test_call_in_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        FilterCallIn(url="https://x", http_method="GET", nope=1)  # type: ignore[call-arg]
