from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BackendHealth(BaseModel):
    """Statut de santé d'un backend MCP, dérivé du dernier monitoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["up", "down", "unknown"]
    error: str | None = None


_HEALTH: dict[str, BackendHealth] = {}


def set_health(backend_id: str, health: BackendHealth) -> None:
    _HEALTH[backend_id] = health


def get_health(backend_id: str) -> BackendHealth:
    return _HEALTH.get(backend_id, BackendHealth(status="unknown"))


def health_snapshot() -> dict[str, BackendHealth]:
    return dict(_HEALTH)


def reset_health() -> None:
    _HEALTH.clear()
