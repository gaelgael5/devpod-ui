"""Validation du format de limite mémoire (enabler 59864c37)."""
from __future__ import annotations

import pytest

from portal.config.models import DevpodDefaults, WorkspaceSpec


@pytest.mark.parametrize("value", ["4g", "512m", "1024", "2G", " 8g ", ""])
def test_memory_limit_valid_formats(value: str) -> None:
    ws = WorkspaceSpec(name="dev", source="github.com/o/r", memory_limit=value)
    assert ws.memory_limit == value.strip().lower()


@pytest.mark.parametrize("value", ["abc", "-1g", "4gb", "g4", "4.5g", "4 g"])
def test_memory_limit_invalid_formats_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        WorkspaceSpec(name="dev", source="github.com/o/r", memory_limit=value)


def test_devpod_defaults_memory_limit_900m_and_validated() -> None:
    # Décision d'exploitation du 2026-07-26 : 900 Mo par défaut, paramétrable
    # (PUT /admin/workspace-defaults + surcharge par workspace).
    assert DevpodDefaults().memory_limit == "900m"
    assert DevpodDefaults(memory_limit="6G").memory_limit == "6g"
    assert DevpodDefaults(memory_limit="").memory_limit == ""
    with pytest.raises(ValueError):
        DevpodDefaults(memory_limit="beaucoup")
