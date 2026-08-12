"""Contrat des événements applicatifs : registre fermé + enveloppe unique.

Un événement est un fait accompli (participe passé), émis par la couche
service APRÈS le succès de l'opération métier — jamais une commande.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Registre fermé : un type inconnu est une faute de programmation, rejetée à
# l'émission comme à l'abonnement. Convention : domaine.verbe_au_passé.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "user.created",
        "user.refreshed",
        "user.connected",
        "user.disconnected",
        "user.deleted",
        "user.paused",
        "user.resumed",
        "workspace.created",
        "workspace.updated",
        "workspace.deleted",
        "workspace.stopped",
        "workspace.restarted",
        "session.created",
        "session.closed",
        "test_server.created",
        "test_server.updated",
        "test_server.deleted",
        "compose_service.started",
        "compose_service.stopped",
        "skill.available",
    }
)


class AppEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Login de l'utilisateur à l'origine de l'action, ou "system".
    actor: str
    # Nom du workspace concerné (sans le préfixe login), None si hors workspace.
    workspace: str | None = None
    # Payload libre propre au type d'événement (clés stables par type).
    subject: dict[str, Any] = Field(default_factory=dict)
    # operation_id d'origine quand l'action passe par launch_operation.
    correlation_id: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"type d'événement inconnu: {v!r}")
        return v
