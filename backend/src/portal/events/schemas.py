"""Catalogue des events produits vers le workflow : `eventCode` + `dataSchema`.

Le portail émet un registre **fermé** d'events internes (`EVENT_TYPES`). Ce module
en dérive la vue **producteur** conforme au contrat workflow :

- chaque type interne `objet.action` devient un `eventCode` versionné
  `devpod.objet.action.v1` (format `domaine.objet.action.vN` imposé par la norme) ;
- chaque `eventCode` porte un `dataSchema` (JSON Schema Draft 2020-12) décrivant ses
  **champs métier à la racine** de l'enveloppe (pas de wrapper `data`).

Le catalogue et les schémas sont statiques (dérivés du code) : leur `revision`/`hash`
ne changent que si ce fichier change — exactement la sémantique de refresh attendue
côté workflow.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import EVENT_TYPES

# Version de l'enveloppe (champ système `_specVersion`).
SPEC_VERSION = "1.0"

# Préfixe de domaine du producteur (première composante de `domaine.objet.action.vN`).
_DOMAIN = "devpod"

# Version courante du type métier de chaque event (le `vN` du code).
_EVENT_VERSION = 1


def event_code_for(event_type: str) -> str:
    """`objet.action` interne → `devpod.objet.action.v1`."""
    return f"{_DOMAIN}.{event_type}.v{_EVENT_VERSION}"


# Map dérivée du registre fermé : garantit une couverture exhaustive d'EVENT_TYPES.
EVENT_CODE_BY_TYPE: dict[str, str] = {t: event_code_for(t) for t in sorted(EVENT_TYPES)}


def _obj(
    required: list[str],
    properties: dict[str, Any],
) -> dict[str, Any]:
    """Fabrique un JSON Schema d'objet permissif (champs métier à la racine)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": required,
        "properties": properties,
        # Permissif : un champ métier ajouté sans bump de version n'est pas rejeté.
        "additionalProperties": True,
    }


_STR = {"type": "string"}
_STR_OR_NULL = {"type": ["string", "null"]}

# dataSchema par type interne (les champs métier vivent à la racine de l'enveloppe :
# `actor` et `workspace` de l'AppEvent + les clés du `subject`).
_DATA_SCHEMA_BY_TYPE: dict[str, dict[str, Any]] = {
    "workspace.created": _obj(
        ["actor", "workspace", "ws_id", "node"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR, "node": _STR},
    ),
    "workspace.restarted": _obj(
        ["actor", "workspace", "ws_id", "node"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR, "node": _STR},
    ),
    "workspace.stopped": _obj(
        ["actor", "workspace", "ws_id"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR},
    ),
    "workspace.deleted": _obj(
        ["actor", "workspace", "ws_id"],
        {
            "actor": _STR,
            "workspace": _STR,
            "ws_id": _STR,
            "recovery_branch": _STR_OR_NULL,
        },
    ),
    "session.created": _obj(
        ["actor", "workspace", "session"],
        {
            "actor": _STR,
            "workspace": _STR,
            "session": _STR,
            "start_recipe": _STR_OR_NULL,
            "command": _STR,
        },
    ),
    "session.closed": _obj(
        ["actor", "workspace", "session"],
        {"actor": _STR, "workspace": _STR, "session": _STR},
    ),
    "compose_service.started": _obj(
        ["actor", "deployment_uid", "deployment_id", "template_id", "node_id", "action"],
        {
            "actor": _STR,
            "workspace": _STR_OR_NULL,
            "deployment_uid": _STR,
            "deployment_id": _STR,
            "template_id": _STR,
            "node_id": _STR,
            "action": _STR,
        },
    ),
    "compose_service.stopped": _obj(
        ["actor", "deployment_uid", "deployment_id", "template_id", "node_id", "action"],
        {
            "actor": _STR,
            "workspace": _STR_OR_NULL,
            "deployment_uid": _STR,
            "deployment_id": _STR,
            "template_id": _STR,
            "node_id": _STR,
            "action": _STR,
        },
    ),
    "test_server.created": _obj(
        ["actor", "workspace", "host_name", "alias", "address", "hypervisor"],
        {
            "actor": _STR,
            "workspace": _STR,
            "host_name": _STR,
            "alias": _STR,
            "address": _STR,
            "hypervisor": _STR,
        },
    ),
    "test_server.updated": _obj(
        ["actor", "workspace", "host_name", "alias", "address"],
        {
            "actor": _STR,
            "workspace": _STR,
            "host_name": _STR,
            "alias": _STR,
            "address": _STR,
            "password_changed": {"type": "boolean"},
        },
    ),
    "test_server.deleted": _obj(
        ["actor", "workspace", "host_name", "alias"],
        {"actor": _STR, "workspace": _STR, "host_name": _STR, "alias": _STR},
    ),
    "skill.available": _obj(
        ["actor", "workspace", "skill_id", "installed_hash"],
        {
            "actor": _STR,
            "workspace": _STR,
            "skill_id": _STR,
            "installed_hash": _STR,
        },
    ),
}

# Vérrou de cohérence au chargement : tout type interne DOIT avoir un dataSchema.
_missing = sorted(EVENT_TYPES - _DATA_SCHEMA_BY_TYPE.keys())
if _missing:  # pragma: no cover - garde de développement
    raise RuntimeError(f"dataSchema manquant pour les events: {_missing}")

# dataSchema indexé par eventCode (vue producteur).
DATA_SCHEMA_BY_CODE: dict[str, dict[str, Any]] = {
    event_code_for(t): schema for t, schema in _DATA_SCHEMA_BY_TYPE.items()
}


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def schema_hash(event_code: str) -> str:
    """`sha256:…` du dataSchema canonique d'un eventCode."""
    return "sha256:" + hashlib.sha256(_canonical(DATA_SCHEMA_BY_CODE[event_code])).hexdigest()


def catalog() -> dict[str, Any]:
    """Catalogue `{revision, specVersion, events[]}` (US découverte §5.1).

    `revision` est le sha256 de l'ensemble (codes + schémas) : il ne change que si le
    catalogue ou l'un de ses schémas change — refresh bon marché côté workflow.
    """
    events = [
        {
            "eventCode": code,
            "latestVersion": _EVENT_VERSION,
            "title": code,
            "description": f"Event {code} émis par le portail devpod.",
            "deprecated": False,
        }
        for code in sorted(DATA_SCHEMA_BY_CODE)
    ]
    revision_material = [
        {"eventCode": code, "hash": schema_hash(code)} for code in sorted(DATA_SCHEMA_BY_CODE)
    ]
    revision = "sha256:" + hashlib.sha256(_canonical(revision_material)).hexdigest()
    return {"revision": revision, "specVersion": SPEC_VERSION, "events": events}


def schema_version(event_code: str, version: int) -> dict[str, Any] | None:
    """`{eventCode, version, dataSchema, hash}` (US découverte §5.2), ou None si inconnu."""
    if event_code not in DATA_SCHEMA_BY_CODE or version != _EVENT_VERSION:
        return None
    return {
        "eventCode": event_code,
        "version": _EVENT_VERSION,
        "dataSchema": DATA_SCHEMA_BY_CODE[event_code],
        "hash": schema_hash(event_code),
    }


def schema_versions(event_code: str) -> list[int] | None:
    """Liste des versions disponibles d'un eventCode (US découverte §5.3), ou None si inconnu."""
    if event_code not in DATA_SCHEMA_BY_CODE:
        return None
    return [_EVENT_VERSION]
