"""On-behalf-of : propagation signée de l'identité humaine vers un backend MCP.

Quand un backend est marqué `forward_identity`, le portail ajoute à l'appel sortant
trois en-têtes qui disent « cet appel est fait pour le compte de l'utilisateur X » :

    x-portal-actor            : le principal humain (owner_login de la session)
    x-portal-actor-timestamp  : instant d'émission (unix, secondes) — anti-rejeu
    x-portal-actor-signature  : HMAC-SHA256 hex de "<actor>\\n<timestamp>"

Le secret de signature est la **clé API du backend** — que seul le portail détient
(le client/agent ne la connaît pas). Un client ne peut donc pas forger la signature :
le backend n'accepte l'identité que si la signature est valide, sinon il l'ignore.
C'est le même algorithme HMAC-SHA256 que le relais d'events (`events/egress`).
"""

from __future__ import annotations

import hmac
from hashlib import sha256

ACTOR_HEADER = "x-portal-actor"
TIMESTAMP_HEADER = "x-portal-actor-timestamp"
SIGNATURE_HEADER = "x-portal-actor-signature"


def _canonical(actor: str, timestamp: int) -> bytes:
    """Octets stables signés puis vérifiés à l'identique côté service."""
    return f"{actor}\n{timestamp}".encode()


def sign_actor(actor: str, timestamp: int, secret: str) -> str:
    """HMAC-SHA256 hex du couple (actor, timestamp) avec le secret partagé."""
    return hmac.new(secret.encode(), _canonical(actor, timestamp), sha256).hexdigest()


def build_obo_headers(actor: str, secret: str, *, now: int) -> dict[str, str]:
    """En-têtes on-behalf-of signés pour l'appel sortant vers le backend."""
    return {
        ACTOR_HEADER: actor,
        TIMESTAMP_HEADER: str(now),
        SIGNATURE_HEADER: sign_actor(actor, now, secret),
    }
