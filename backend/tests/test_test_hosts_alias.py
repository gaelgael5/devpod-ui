# backend/tests/test_test_hosts_alias.py
"""Attribution d'alias testN aux machines de test (partie pure)."""
from __future__ import annotations

from portal.db.test_hosts import next_test_alias


def test_first_alias_is_test1() -> None:
    assert next_test_alias([]) == "test1"


def test_increments_when_contiguous() -> None:
    assert next_test_alias(["test1"]) == "test2"
    assert next_test_alias(["test1", "test2"]) == "test3"


def test_reuses_smallest_free_number() -> None:
    # test1 libéré → la prochaine reprend test1.
    assert next_test_alias(["test2"]) == "test1"
    # comble le trou laissé par test2.
    assert next_test_alias(["test1", "test3"]) == "test2"


def test_ignores_non_conforming_aliases() -> None:
    # Valeurs hors forme testN sont ignorées dans le calcul.
    assert next_test_alias(["foo", "bar"]) == "test1"
    assert next_test_alias(["test1", "", "x"]) == "test2"


def test_handles_unordered_input() -> None:
    assert next_test_alias(["test3", "test1", "test2"]) == "test4"
