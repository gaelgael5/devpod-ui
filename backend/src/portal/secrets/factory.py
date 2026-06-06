from __future__ import annotations

from pathlib import Path

import structlog

from .backends.base import SecretsBackend
from .backends.harpocrate import HarpocrateBackend
from .backends.inline import InlineBackend

_log = structlog.get_logger(__name__)


def create_backend(
    *,
    backend_type: str,
    url: str = "",
    api_key: str,
    base_path: str,
    user_secrets_path: Path,
) -> SecretsBackend:
    """Crée le backend approprié.

    Si backend_type="harpocrate" et api_key vide → fallback sur InlineBackend
    avec un warning structlog (loggé une seule fois à la création).
    """
    if backend_type == "harpocrate":
        if not api_key:
            _log.warning(
                "harpocrate_api_key_empty_fallback_inline",
                reason="api_key is empty, falling back to inline backend",
            )
            return InlineBackend(user_secrets_path=user_secrets_path, base_path=base_path)
        return HarpocrateBackend(url=url, api_key=api_key, base_path=base_path)
    # backend_type == "inline"
    return InlineBackend(user_secrets_path=user_secrets_path, base_path=base_path)
