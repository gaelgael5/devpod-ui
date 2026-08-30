"""Abonnements : état, transitions, et idempotence des webhooks.

**Une résiliation n'est pas une suppression de compte.** La distinction est
structurante et ce module la tient :

- **Résiliation** : l'abonnement s'arrête, le compte demeure, et l'utilisateur
  peut REPRENDRE plus tard — c'est `reprendre()`. `resilie` est donc un état
  clos, pas un état définitif.
- **Suppression de compte** : acte définitif, sans retour. Elle ne se joue pas
  ici : c'est la ligne `users` qui disparaît, et les abonnements suivent en
  `ON DELETE CASCADE`.

Deux mécanismes qui se paient cher s'ils sont approximatifs :

1. **Aucun événement de cycle ne rouvre un abonnement résilié.** Les
   fournisseurs de paiement ne garantissent pas l'ordre de livraison de leurs
   webhooks : un `renouvellement` peut arriver APRÈS la `resiliation` qu'il
   précède chronologiquement. Il ne doit pas ressusciter un abonnement clos —
   seule une reprise explicite le rouvre.
2. **Un événement déjà vu est ignoré, pas rejoué.** Les fournisseurs renvoient
   leurs notifications — c'est leur fonctionnement nominal, pas un incident. La
   clef `(provider_slug, provider_event_id)` est unique en base ; ce module
   porte la décision côté application.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import PolitiqueRelance

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

#: États CLOS : aucun événement de cycle de facturation ne les fait sortir.
#:
#: Clos ne veut pas dire définitif. Un abonnement résilié se reprend — par
#: `reprendre()`, qui refige le prix au tarif du jour. Ce qui est refusé ici,
#: c'est la réouverture ACCIDENTELLE par un webhook du cycle précédent arrivé
#: en retard. Le seul état définitif est la disparition du compte, qui n'est pas
#: un état d'abonnement.
ETATS_CLOS: frozenset[str] = frozenset({"resilie"})


class TransitionRefusee(Exception):
    """L'événement ne peut pas s'appliquer à l'état courant (FR)."""


class RepriseRefusee(Exception):
    """L'abonnement n'est pas dans un état où une reprise a un sens (FR)."""


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
    #: Échecs de prélèvement CONSÉCUTIFS de l'épisode en cours. Remis à zéro dès
    #: qu'un paiement passe — ce n'est pas un compteur de vie.
    payment_attempts: int = Field(default=0, ge=0)
    #: Prochaine relance programmée. `None` = rien en attente.
    next_retry_at: datetime | None = None
    trial_end: datetime | None = None
    current_period_end: datetime | None = None
    #: Jour d'arrêt du forfait, calculé à la souscription depuis la durée de
    #: l'offre. `None` = pas encore posé. Ce n'est pas `current_period_end`, qui
    #: est la fin de la PÉRIODE facturée côté fournisseur : celle-ci se
    #: renouvelle, le terme du forfait, lui, arrête le service.
    ends_at: datetime | None = None
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

        `echec_paiement` reste ouvert : on ne coupe pas au premier prélèvement
        refusé, qui échoue souvent pour une raison passagère. La période de
        grâce est exactement la fenêtre de relance — au-delà de la dernière
        tentative, l'abonnement passe `resilie` et se ferme.
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
    """État résultant de l'application d'un événement de cycle.

    Lève `TransitionRefusee` depuis un état clos. Ce n'est pas une fin de vie :
    la reprise d'un abonnement résilié existe et passe par `reprendre()`, qui
    refige le prix. Ce qui est refusé ici, c'est qu'un webhook en retard rouvre
    le service tout seul, au tarif d'hier.
    """
    if courant in ETATS_CLOS:
        raise TransitionRefusee(
            f"abonnement {courant} : l'événement {kind} ne s'applique plus — "
            "une reprise passe par reprendre()"
        )
    return ETAT_APRES[kind]


def _apres_echec(sub: Subscription, moment: datetime, politique: PolitiqueRelance) -> Subscription:
    """Décide la suite d'un prélèvement refusé : relancer, ou couper.

    On ne coupe pas au premier refus — plafond mensuel, carte expirée du matin,
    ces échecs se réparent seuls. Mais on ne relance pas indéfiniment un service
    non payé : à la dernière tentative, l'abonnement est RÉSILIÉ, donc de façon
    réversible (le compte demeure, la reprise reste ouverte).
    """
    etat_apres(sub.state, "echec_paiement")  # garde : rien à couper si déjà clos
    tentatives = sub.payment_attempts + 1

    if tentatives >= politique.tentatives_max:
        return sub.model_copy(
            update={
                "state": "resilie",
                "payment_attempts": tentatives,
                "next_retry_at": None,
                "state_changed_at": moment,
            }
        )

    return sub.model_copy(
        update={
            "state": "echec_paiement",
            "payment_attempts": tentatives,
            "next_retry_at": moment + timedelta(hours=politique.delai_heures),
            "state_changed_at": moment,
        }
    )


def appliquer(
    sub: Subscription,
    event: SubscriptionEvent,
    moment: datetime,
    politique: PolitiqueRelance | None = None,
) -> Subscription:
    """Applique un événement et rend l'abonnement mis à jour.

    Fonction pure : elle ne touche pas la base, elle décide. La persistance et
    l'écriture de la ligne d'idempotence appartiennent à l'appelant, dans la
    même transaction.
    """
    if event.kind == "echec_paiement":
        return _apres_echec(sub, moment, politique or PolitiqueRelance())

    nouvel_etat = etat_apres(sub.state, event.kind)
    maj: dict[str, object] = {"state": nouvel_etat, "state_changed_at": moment}
    if event.kind in {"activation", "renouvellement"}:
        # Le paiement est passé : l'épisode d'échec est clos, la relance
        # programmée n'a plus lieu d'être.
        maj["payment_attempts"] = 0
        maj["next_retry_at"] = None
    return sub.model_copy(update=maj)


def fin_de_forfait(debut: datetime, duration_days: int) -> datetime:
    """Instant d'échéance d'un forfait souscrit à `debut` : jour ET heure.

    **L'heure de souscription est conservée.** Un forfait pris le 15 janvier à
    9 h 30 échoit le 14 février à 9 h 30, pas à minuit : arrondir au jour
    offrirait — ou retirerait — jusqu'à vingt-quatre heures de service à chaque
    souscription, et le renouvellement se déclencherait pour tout le monde à la
    même seconde.

    **La précision s'arrête à la minute.** Les secondes sont un artefact de
    l'instant où le webhook est arrivé, pas une donnée commerciale : les garder
    ferait échoir deux abonnements pris dans la même minute à des instants
    différents, sans que personne ne puisse expliquer pourquoi.

    `timedelta` et non une arithmétique de mois : « 30 jours » est une durée
    exacte, là où « un mois » n'en est pas une. C'est aussi ce que l'offre
    déclare — sa durée est en jours.
    """
    if duration_days <= 0:
        raise ValueError("duration_days : un forfait dure au moins un jour")
    echeance = debut + timedelta(days=duration_days)
    return echeance.replace(second=0, microsecond=0)


def relance_due(sub: Subscription, maintenant: datetime) -> bool:
    """L'heure de retenter le prélèvement est-elle venue ?

    Ce que le scheduler interroge. Un abonnement sans relance programmée n'est
    jamais dû : c'est ce qui distingue « en attente de relance » de « coupé ».
    """
    return (
        sub.state == "echec_paiement"
        and sub.next_retry_at is not None
        and sub.next_retry_at <= maintenant
    )


def reprendre(
    sub: Subscription,
    *,
    currency: str,
    amount_minor: int,
    moment: datetime,
    offer_slug: str | None = None,
    provider_subscription_id: str = "",
    en_essai: bool = False,
    duration_days: int | None = None,
) -> Subscription:
    """Reprend un abonnement résilié : le compte n'a jamais été supprimé.

    Une reprise est un ACTE COMMERCIAL NEUF, pas une annulation de la
    résiliation. Deux conséquences dans la signature :

    - **le prix est refigé** au tarif du jour. L'instantané d'origine protégeait
      l'abonné pendant la vie de son abonnement ; il ne lui garantit pas un
      tarif d'archive à la reprise ;
    - **l'identifiant côté fournisseur est remis à zéro.** L'ancien objet est
      clos chez le fournisseur : le garder ferait router les webhooks de la
      reprise vers un abonnement mort.

    `offer_slug` permet de reprendre sur une autre offre — le cas courant quand
    le catalogue a bougé entre temps.

    `duration_days` refixe le TERME : une reprise repart pour une durée pleine.
    Reconduire l'ancienne date rouvrirait un abonnement déjà expiré. Sans
    durée fournie, on ne devine pas — le terme reste à poser.
    """
    if sub.state not in ETATS_CLOS:
        raise RepriseRefusee(f"abonnement {sub.state} : rien à reprendre, il n'est pas résilié")
    return sub.model_copy(
        update={
            "state": "essai" if en_essai else "actif",
            "offer_slug": offer_slug or sub.offer_slug,
            "currency": currency,
            "amount_minor": amount_minor,
            "provider_subscription_id": provider_subscription_id,
            # Ardoise nette : les échecs de l'abonnement clos ne comptent pas
            # contre la reprise, sinon un seul refus la couperait aussitôt.
            "payment_attempts": 0,
            "next_retry_at": None,
            "trial_end": None,
            "current_period_end": None,
            "ends_at": fin_de_forfait(moment, duration_days) if duration_days else None,
            "state_changed_at": moment,
        }
    )
