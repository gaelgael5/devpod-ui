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

# Identité du propriétaire, injectée dans les events workspace/session (comme user.*)
# pour matcher les systèmes tiers (Termix : clé = `sub`). Tous optionnels.
_OWNER = {"login": _STR, "sub": _STR, "email": _STR, "identity": _STR}

# « Le forfait choisi » sur les événements user.* (fiche Automate — événements
# user) : slug de l'offre de l'abonnement OUVERT du compte, null sans abonnement.
_OFFRE = {"offre_slug": _STR_OR_NULL}

# dataSchema par type interne (les champs métier vivent à la racine de l'enveloppe :
# `actor` et `workspace` de l'AppEvent + les clés du `subject`).
_DATA_SCHEMA_BY_TYPE: dict[str, dict[str, Any]] = {
    # Identité utilisateur : `sub` (ancre OIDC) = clé de matching côté systèmes tiers.
    "user.created": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR, "email": _STR, "identity": _STR, **_OFFRE},
    ),
    "user.refreshed": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR, "email": _STR, "identity": _STR, **_OFFRE},
    ),
    # Session de connexion ouverte / fermée (login OIDC ou local ; logout).
    "user.connected": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR, "email": _STR, "identity": _STR, **_OFFRE},
    ),
    "user.disconnected": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR},
    ),
    # Cycle de vie compte devpod (émetteurs à câbler quand la désactivation/suppression
    # d'utilisateur existera) : deleted = compte retiré ; paused = désactivé ; resumed = réactivé.
    "user.deleted": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR},
    ),
    "user.paused": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR},
    ),
    "user.resumed": _obj(
        ["actor", "login", "sub"],
        {"actor": _STR, "login": _STR, "sub": _STR},
    ),
    "workspace.created": _obj(
        ["actor", "workspace", "ws_id", "node"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR, "node": _STR, **_OWNER},
    ),
    "workspace.restarted": _obj(
        ["actor", "workspace", "ws_id", "node"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR, "node": _STR, **_OWNER},
    ),
    # Émis par le rattrapage (backfill) et l'injection d'event de test pour signaler
    # qu'un workspace « a bougé » sans transition de cycle de vie (re-synchro Termix).
    "workspace.updated": _obj(
        ["actor", "workspace", "ws_id"],
        {
            "actor": _STR,
            "workspace": _STR,
            "ws_id": _STR,
            "node": _STR_OR_NULL,
            "address": _STR_OR_NULL,
            "status": _STR_OR_NULL,
            **_OWNER,
        },
    ),
    "workspace.stopped": _obj(
        ["actor", "workspace", "ws_id"],
        {"actor": _STR, "workspace": _STR, "ws_id": _STR, **_OWNER},
    ),
    "workspace.deleted": _obj(
        ["actor", "workspace", "ws_id"],
        {
            "actor": _STR,
            "workspace": _STR,
            "ws_id": _STR,
            "recovery_branch": _STR_OR_NULL,
            **_OWNER,
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
    # Cycle d'abonnement. Noms de champs DÉCIDÉS par la fiche « Automate —
    # événements user (forfait) » : user_id, user_email, offre_slug,
    # subscription_id (clé d'idempotence des règles d'automate). `variables` =
    # les variables personnalisées de l'offre, schéma libre clé/valeur tant que
    # sa structure exacte n'est pas cadrée.
    **{
        t: _obj(
            ["actor", "user_id", "offre_slug", "subscription_id", "hosting_type"],
            {
                "actor": _STR,
                "user_id": _STR,
                "user_email": _STR_OR_NULL,
                "offre_slug": _STR,
                "subscription_id": _STR,
                "hosting_type": _STR,
                "state": _STR,
                "variables": {"type": "object"},
            },
        )
        for t in (
            "subscription.trial_started",
            "subscription.activated",
            "subscription.renewed",
            "subscription.payment_failed",
            "subscription.cancelled",
        )
    },
    # L'expiration du délai de rétention porte en plus l'état qui l'a armée et
    # le délai appliqué : c'est ce que la règle de destruction doit relire.
    "subscription.retention_expired": _obj(
        ["actor", "user_id", "offre_slug", "subscription_id", "hosting_type", "state"],
        {
            "actor": _STR,
            "user_id": _STR,
            "user_email": _STR_OR_NULL,
            "offre_slug": _STR,
            "subscription_id": _STR,
            "hosting_type": _STR,
            "state": _STR,
            "retention_jours": {"type": "integer"},
            "state_changed_at": _STR_OR_NULL,
            "variables": {"type": "object"},
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


def variables_for(event_type: str) -> list[str]:
    """Variables de template disponibles pour un event (namespace `event.*`).

    Dérivées du dataSchema : `event.type` + un `event.<champ>` par propriété métier.
    Contextuel : `event.workspace` n'apparaît que pour les events qui en portent un
    (schéma), pas pour `user.created` par exemple.
    """
    schema = _DATA_SCHEMA_BY_TYPE.get(event_type)
    props = list(schema["properties"].keys()) if schema else []
    return ["event.type", *(f"event.{p}" for p in props)]


def variables_by_type() -> dict[str, list[str]]:
    """Catalogue {type interne → variables} pour l'IHM (palette contextuelle)."""
    return {t: variables_for(t) for t in sorted(EVENT_TYPES)}
