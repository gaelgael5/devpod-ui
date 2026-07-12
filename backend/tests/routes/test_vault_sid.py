"""Bug 031 : _sid (routes/vault.py) doit fail-closed sur un session_id vide,
plutôt que de laisser toute opération vault indexer sur _sessions['']."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from portal.routes.vault import _sid


def _request(session: dict) -> SimpleNamespace:
    return SimpleNamespace(session=session)


def test_sid_returns_session_id_when_present() -> None:
    assert _sid(_request({"session_id": "abc123"})) == "abc123"


def test_sid_raises_401_when_missing() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _sid(_request({}))
    assert exc_info.value.status_code == 401


def test_sid_raises_401_when_empty_string() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _sid(_request({"session_id": ""}))
    assert exc_info.value.status_code == 401
