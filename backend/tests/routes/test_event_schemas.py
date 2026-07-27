"""API publique de découverte des schémas d'events (`/schemas`)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.events.models import EVENT_TYPES
from portal.routes.event_schemas import router


def _client() -> TestClient:
    # App minimale : la découverte est publique et sans DB — pas besoin du lifespan.
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_catalog_endpoint_is_public_and_lists_all_events() -> None:
    resp = _client().get("/schemas")
    assert resp.status_code == 200
    body = resp.json()
    assert body["specVersion"] == "1.0"
    assert body["revision"].startswith("sha256:")
    # Couverture exhaustive du registre fermé (dérivé d'EVENT_TYPES, jamais figé).
    assert len(body["events"]) == len(EVENT_TYPES)


def test_schema_endpoint_returns_dataschema() -> None:
    resp = _client().get("/schemas/devpod.workspace.created.v1/versions/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eventCode"] == "devpod.workspace.created.v1"
    assert body["version"] == 1
    assert body["dataSchema"]["type"] == "object"


def test_unknown_code_and_version_are_404() -> None:
    c = _client()
    assert c.get("/schemas/devpod.workspace.created.v1/versions/2").status_code == 404
    assert c.get("/schemas/nope.x.v1/versions/1").status_code == 404
    assert c.get("/schemas/nope.x.v1/versions").status_code == 404


def test_versions_enumeration() -> None:
    resp = _client().get("/schemas/devpod.session.closed.v1/versions")
    assert resp.status_code == 200
    assert resp.json()["versions"] == [1]
