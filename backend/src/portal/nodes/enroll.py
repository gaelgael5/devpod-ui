from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from ..config.store import _data_root

_log = structlog.get_logger(__name__)

# §E-27 : TTL court pour les tokens de join
_TOKEN_TTL_SECONDS = 3600  # 1h

_token_locks: dict[str, asyncio.Lock] = {}


def clear_token_locks() -> None:
    _token_locks.clear()


def _token_dir() -> Path:
    return _data_root() / "tokens"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_path(token: str) -> Path:
    return _token_dir() / f"{_token_hash(token)}.json"


def _get_token_lock(token: str) -> asyncio.Lock:
    return _token_locks.setdefault(_token_hash(token), asyncio.Lock())


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def generate_token(node_name: str, address: str) -> str:
    """Génère un token aléatoire et le stocke hashé avec TTL. §E-27."""
    token = secrets.token_urlsafe(32)
    data: dict[str, Any] = {
        "node_name": node_name,
        "address": address,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=_TOKEN_TTL_SECONDS)).isoformat(),
        "used": False,
    }
    _atomic_write_json(_token_path(token), data)
    _log.info("join_token_generated", node_name=node_name)
    return token


async def consume_token(token: str) -> tuple[str, str]:
    """Valide et consomme un join token. Retourne (node_name, address). §E-27."""
    async with _get_token_lock(token):
        path = _token_path(token)
        if not path.exists():
            raise ValueError("Token not found or already used")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("used"):
            raise ValueError("Token already used")
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(UTC) > expires_at:
            raise ValueError("Token expired")
        data["used"] = True
        _atomic_write_json(path, data)
        _log.info("join_token_consumed", node_name=data["node_name"])
        return data["node_name"], data["address"]
