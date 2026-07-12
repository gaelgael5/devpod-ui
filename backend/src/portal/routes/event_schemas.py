"""API de découverte des schémas d'events (contrat producteur workflow §5).

Endpoints **publics en lecture seule** — le workflow les tire à l'import/refresh d'une
source. Aucun secret n'y transite (uniquement des `eventCode` et leurs JSON Schema),
donc pas de dépendance d'authentification : le catalogue est dérivé statiquement du
registre fermé d'events du portail.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..events import schemas

router = APIRouter(tags=["event-schemas"])


@router.get("/schemas")
async def get_catalog() -> dict[str, Any]:
    """Catalogue `{revision, specVersion, events[]}` (§5.1)."""
    return schemas.catalog()


@router.get("/schemas/{event_code}/versions")
async def get_versions(event_code: str) -> dict[str, Any]:
    """Énumération des versions d'un eventCode (§5.3)."""
    versions = schemas.schema_versions(event_code)
    if versions is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown eventCode")
    return {"eventCode": event_code, "versions": versions}


@router.get("/schemas/{event_code}/versions/{version}")
async def get_schema(event_code: str, version: int) -> dict[str, Any]:
    """Schéma d'une version d'un eventCode : `{eventCode, version, dataSchema, hash}` (§5.2)."""
    payload = schemas.schema_version(event_code, version)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown eventCode or version")
    return payload
