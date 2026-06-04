from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_token_locks() -> None:
    from portal.nodes import enroll

    enroll.clear_token_locks()
