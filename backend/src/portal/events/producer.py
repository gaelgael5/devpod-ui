"""Mapping AppEvent interne → enveloppe plate normée (contrat producteur workflow).

L'enveloppe est **plate** : les cinq champs système requis (`_eventId`, `_eventCode`,
`_occurredAt`, `_source`, `_specVersion`) coexistent à la racine avec les champs métier
(`actor`, `workspace`, et les clés du `subject`). Aucun wrapper `data`, aucun champ de
contexte de destination (dérivé serveur-side côté workflow), aucun pointeur de schéma.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .models import AppEvent
from .schemas import EVENT_CODE_BY_TYPE, SPEC_VERSION


def to_envelope(event: AppEvent, *, source_uri: str) -> dict[str, Any]:
    """Construit l'enveloppe plate normée à partir d'un AppEvent.

    - `_eventId` : UUID canonique (forme à tirets) — dérivé de l'event_id interne ;
    - `_eventCode` : `devpod.objet.action.v1` ;
    - `_occurredAt` : RFC 3339 avec timezone (isoformat d'un datetime tz-aware) ;
    - `_traceId` : optionnel, depuis `correlation_id` ;
    - champs métier à la racine : `subject` puis `actor`/`workspace` (autoritaires).
    """
    envelope: dict[str, Any] = {
        "_eventId": str(uuid.UUID(event.event_id)),
        "_eventCode": EVENT_CODE_BY_TYPE[event.type],
        "_occurredAt": event.occurred_at.isoformat(),
        "_source": source_uri,
        "_specVersion": SPEC_VERSION,
    }
    if event.correlation_id:
        envelope["_traceId"] = event.correlation_id
    # Champs métier : subject d'abord (jamais de clé préfixée `_`, qui empièterait sur
    # l'espace système), puis actor/workspace qui font foi.
    for key, value in event.subject.items():
        if not key.startswith("_"):
            envelope[key] = value
    envelope["actor"] = event.actor
    if event.workspace is not None:
        envelope["workspace"] = event.workspace
    return envelope


def build_test_envelope(source_uri: str) -> dict[str, Any]:
    """Enveloppe d'un event de **test** normalisé `{appli}.testevent.v1`.

    `{appli}` est dérivée du dernier segment de `source_uri` (ex. `urn:yoops:devpod`
    → `devpod`). Cet `_eventCode` n'est pas au catalogue `/schemas` : le workflow
    l'accepte comme event non validé (Norme §2.4) — suffisant pour tester la
    connectivité et l'ingestion signée sans polluer les schémas réels.
    """
    app = source_uri.rsplit(":", 1)[-1] or "app"
    return {
        "_eventId": str(uuid.uuid4()),
        "_eventCode": f"{app}.testevent.v1",
        "_occurredAt": datetime.now(UTC).isoformat(),
        "_source": source_uri,
        "_specVersion": SPEC_VERSION,
        "test": True,
    }
