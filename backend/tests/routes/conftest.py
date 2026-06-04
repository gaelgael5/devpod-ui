from __future__ import annotations

import os

import pytest

_ENV_KEYS = ("PORTAL_DATA_ROOT", "SESSION_SECRET_KEY")


@pytest.fixture(autouse=True)
def _clean_env(request: pytest.FixtureRequest):
    """Restore modified env vars after each test in this package."""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    yield
    import portal.settings as mod

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    mod._settings = None
