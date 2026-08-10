"""Évaluation des filtres d'automate : JSONPath + opérateurs exists/equals/not_equals."""

from __future__ import annotations

import pytest

from portal.automations import filter_eval as fe

_RESP = {
    "users": [
        {"userId": "RT23", "username": "gael", "is_admin": True},
        {"userId": "AB99", "username": "bob", "is_admin": False},
    ]
}


def test_exists_true_when_filter_matches() -> None:
    passed, matches = fe.evaluate(_RESP, '$.users[?(@.username=="gael")]', "exists", None)
    assert passed is True
    assert matches == [{"userId": "RT23", "username": "gael", "is_admin": True}]


def test_exists_false_when_no_match() -> None:
    passed, matches = fe.evaluate(_RESP, '$.users[?(@.username=="ghost")]', "exists", None)
    assert passed is False and matches == []


def test_equals_on_scalar_path() -> None:
    passed, _ = fe.evaluate(_RESP, '$.users[?(@.username=="gael")].is_admin', "equals", "true")
    assert passed is True  # booléen JSON → "true", comparaison insensible à la casse


def test_not_equals() -> None:
    passed, _ = fe.evaluate(_RESP, "$.users[*].username", "not_equals", "carol")
    assert passed is True
    passed2, _ = fe.evaluate(_RESP, "$.users[*].username", "not_equals", "gael")
    assert passed2 is False


def test_invalid_jsonpath_raises() -> None:
    with pytest.raises(ValueError, match="JSONPath invalide"):
        fe.evaluate(_RESP, "$.users[??", "exists", None)


def test_unknown_operator_raises() -> None:
    with pytest.raises(ValueError, match="opérateur inconnu"):
        fe.evaluate(_RESP, "$.users", "matches", None)
