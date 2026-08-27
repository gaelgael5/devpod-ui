"""Abonnements : état, transitions, et idempotence des webhooks.

Deux mécanismes qui se paient cher s'ils sont approximatifs :

1. **`resilie` est terminal.** Les fournisseurs de paiement ne garantissent pas
   l'ordre de livraison de leurs webhooks : un `renouvellement` peut arriver
   APRÈS la `resiliation` qu'il précède chronologiquement. Sans garde, il
   ressusciterait un abonnement fermé.
2. **Un événement déjà vu est ignoré, pas rejoué.** Les fournisseurs renvoient
   leurs notifications — c'est leur fonctionnement nominal, pas un incident. La
   clef `(provider_slug, provider_event_id)` est unique en base ; ce module
   porte la décision côté application.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

SubscriptionState = Literal["essai", "actif", "echec_paiement", "resilie"]
EventKind = Literal["debut_essai", "activation", "renouvellement", "echec_paiement", "resiliation"]

#: État dans lequel chaque événement place l'abonnement. La table est
#: exhaustive : ajouter un type d'événement sans décider de son effet ici est
#: une erreur détectée par les tests, pas un comportement par défaut.
ETAT_APRES: dict[str, SubscriptionState] = {
    "debut_essai": "essai",
    "activation": "actif",
    "renouvellement": "actif",
    "echec_paiement": "echec_paiement",
    "resiliation": "resilie",
}

#: États depuis lesquels plus aucune transition n'est acceptée.
ETATS_TERMINAUX: frozenset[str] = frozenset({"resilie"})


class TransitionRefusee(Exception):
    """L'événement ne peut pas s'appliquer à l'état courant (FR)."""


class Subscription(BaseModel):
    """Abonnement d'un utilisateur à une offre.

    `currency` et `amount_minor` sont un INSTANTANÉ du prix au moment de la
    souscription, pas une lecture du catalogue : celui-ci évolue, un abonné
    garde le prix auquel il a souscrit, et une facture ancienne reste
    reproductible.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    login: str
    offer_slug: str
    provider_slug: str | None = None
    state: SubscriptionState = "essai"
    country_code: str
    currency: str
    amount_minor: int = Field(ge=0)
    provider_subscription_id: str = ""
    trial_end: datetime | None = None
    current_period_end: datetime | None = None
    state_changed_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def _devise(cls, v: str) -> str:
        if not _CURRENCY_RE.match(v):
            raise ValueError(f"devise ISO-4217 attendue (3 lettres majuscules) : {v!r}")
        return v

    @field_validator("country_code")
    @classmethod
    def _pays(cls, v: str) -> str:
        if not _COUNTRY_RE.match(v):
            raise ValueError(f"code pays ISO-3166-1 alpha-2 attendu : {v!r}")
        return v

    @property
    def ouvert(self) -> bool:
        """L'abonnement donne-t-il droit au service ?

        `echec_paiement` reste ouvert : c'est le sens même de la période de
        grâce — on ne coupe pas au premier prélèvement refusé, le scheduler de
        rétention décide de la suite.
        """
        return self.state in {"essai", "actif", "echec_paiement"}


class SubscriptionEvent(BaseModel):
    """Événement d'abonnement reçu d'un fournisseur de paiement."""

    model_config = ConfigDict(extra="forbid")

    kind: EventKind
    provider_slug: str
    provider_event_id: str
    subscription_id: str | None = None
    login: str = ""
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("provider_event_id")
    @classmethod
    def _identifiant(cls, v: str) -> str:
        # Sans identifiant, aucune idempotence possible : on refuse à l'entrée
        # plutôt que de dédupliquer sur une clef vide partagée par tous.
        if not v.strip():
            raise ValueError("provider_event_id est requis pour l'idempotence")
        return v


def cle_idempotence(event: SubscriptionEvent) -> tuple[str, str]:
    """Clef de déduplication d'un webhook, alignée sur l'unique en base."""
    return (event.provider_slug, event.provider_event_id)


def deja_traite(event: SubscriptionEvent, vues: set[tuple[str, str]]) -> bool:
    """Vrai si cet événement a déjà été appliqué."""
    return cle_idempotence(event) in vues


def etat_apres(courant: SubscriptionState, kind: EventKind) -> SubscriptionState:
    """État résultant de l'application d'un événement.

    Lève `TransitionRefusee` depuis un état terminal : un webhook en retard ne
    doit pas rouvrir un abonnement résilié.
    """
    if courant in ETATS_TERMINAUX:
        raise TransitionRefusee(f"abonnement {courant} : l'événement {kind} n'est plus applicable")
    return ETAT_APRES[kind]


def appliquer(sub: Subscription, event: SubscriptionEvent, moment: datetime) -> Subscription:
    """Applique un événement et rend l'abonnement mis à jour.

    Fonction pure : elle ne touche pas la base, elle décide. La persistance et
    l'écriture de la ligne d'idempotence appartiennent à l'appelant, dans la
    même transaction.
    """
    nouvel_etat = etat_apres(sub.state, event.kind)
    if nouvel_etat == sub.state:
        # Renouvellement d'un abonnement déjà actif : rien ne change côté état,
        # mais l'horodatage doit avancer (le scheduler s'en sert).
        return sub.model_copy(update={"state_changed_at": moment})
    return sub.model_copy(update={"state": nouvel_etat, "state_changed_at": moment})
