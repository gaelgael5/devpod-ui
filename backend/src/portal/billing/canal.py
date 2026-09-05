"""Ce qu'un canal de vente doit savoir faire, indépendamment du fournisseur.

Trois responsabilités, et trois seulement :

1. **authentifier** ce qui arrive — un webhook est une route ouverte sur
   l'extérieur, la signature est sa seule protection ;
2. **normaliser** — traduire le vocabulaire du fournisseur vers les cinq
   événements du cycle d'abonnement, qui sont ceux du portail ;
3. **ouvrir un paiement** — et, quand le forfait ne se reconduit pas,
   couper la reconduction que le fournisseur applique par défaut.

Les deux premières sont PURES : elles ne lisent ni base ni réseau, ce qui permet
de vérifier tout le mapping sans compte de paiement. La troisième parle au
réseau, par nécessité — on ne crée pas une session de paiement hors ligne.

**Ce que cette pureté ne prouve pas**, et qu'il ne faut pas croire couvert : que
les charges utiles réelles aient la forme des doublures. C'est précisément là
que ça casse — un format abrégé au lieu du format complet, un champ optionnel
absent en production. Tant qu'aucun compte réel n'a émis un webhook, aucun test
ici ne vaut validation d'un paiement.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .subscriptions import SubscriptionEvent


class SignatureInvalide(Exception):
    """La charge utile n'est pas authentifiée. Elle est jetée, pas rejouée.

    Message volontairement pauvre : ce qui remonte au fournisseur ne doit pas
    dire à un attaquant quelle partie de sa contrefaçon a échoué.
    """


class PaiementImpossible(Exception):
    """Le fournisseur n'a pas ouvert la session de paiement.

    Distincte de `SignatureInvalide` : celle-ci concerne ce qui ENTRE et se
    jette en silence, celle-là ce qui SORT et doit remonter à l'utilisateur —
    il attend une page de paiement qui ne viendra pas.
    """


class DemandePaiement(BaseModel):
    """Ce qu'il faut au canal pour ouvrir une session, et rien de plus.

    Aucun objet du portail n'entre ici — ni `Offer`, ni `Subscription`. Un
    adaptateur qui recevrait nos modèles finirait par lire des champs dont il
    n'a pas besoin, et le jour où l'un d'eux change, c'est l'adaptateur d'un
    fournisseur tiers qui casse.

    `montant_minor` est en unités mineures, entier. Jamais un flottant : c'est
    de l'argent.
    """

    model_config = ConfigDict(extra="forbid")

    #: NOTRE identifiant. Il repart en métadonnée et nous revient par le
    #: webhook — c'est lui qui rattache l'événement à l'abonnement.
    subscription_id: str
    #: Nom du produit tel qu'il s'affichera sur la page de paiement.
    libelle: str
    devise: str = Field(pattern=r"^[A-Z]{3}$")
    montant_minor: int = Field(ge=0)
    #: Terme du forfait, en jours. Toute offre est bornée.
    duree_jours: int = Field(gt=0)
    #: Faux = le forfait s'arrête à son terme. Le fournisseur reconduit par
    #: défaut ; c'est au canal de couper, pas à l'appelant de s'en souvenir.
    reconduction: bool
    #: Pré-remplit la page de paiement. Vide si on ne le connaît pas.
    email: str = ""
    url_succes: str
    url_abandon: str


class CanalDeVente(Protocol):
    """Contrat d'un adaptateur de canal de vente."""

    #: Discriminant, aligné sur `PaymentProvider.kind`.
    kind: str

    def verifier_signature(
        self,
        corps: bytes,
        en_tetes: Mapping[str, str],
        secret: str,
        maintenant: datetime,
    ) -> None:
        """Lève `SignatureInvalide` si la charge n'est pas authentique.

        `corps` est le corps BRUT, octet pour octet. Une signature se calcule
        sur ce qui a été reçu, pas sur un JSON re-sérialisé : reformater le
        corps en amont invalide toutes les signatures, et le symptôme —
        « signature invalide » sur des webhooks parfaitement valides — est
        pénible à rapporter à sa cause.
        """
        ...

    def normaliser(self, payload: Mapping[str, object]) -> SubscriptionEvent | None:
        """Traduit un événement du fournisseur, ou `None` s'il ne nous concerne pas.

        `None` et non une exception : un fournisseur émet quantité
        d'événements dont aucun ne nous regarde. Les traiter comme des erreurs
        remplirait les journaux de bruit et masquerait les vrais échecs.
        """
        ...

    def identifiant_abonnement(self, payload: Mapping[str, object]) -> str | None:
        """Identifiant de l'abonnement chez le fournisseur, ou `None`.

        Pur, comme la normalisation. Permet au portail d'apprendre — et de
        retenir — la clef qui rattachera tous les événements suivants, sans quoi
        chacun arriverait orphelin.
        """
        ...

    async def ouvrir_paiement(self, demande: DemandePaiement, cle_api: str) -> str:
        """Ouvre une session de paiement et rend l'URL où envoyer le client.

        Lève `PaiementImpossible` si le fournisseur refuse. On ne rend jamais
        d'URL vide en cas d'échec : l'appelant redirigerait vers nulle part, et
        le client croirait le paiement engagé.

        L'appel DOIT être idempotent sur `demande.subscription_id` — un client
        qui clique deux fois ne doit pas ouvrir deux sessions, donc payer deux
        fois.
        """
        ...

    async def couper_reconduction(self, provider_subscription_id: str, cle_api: str) -> None:
        """Programme l'arrêt de l'abonnement à la fin de la période en cours.

        Appelée seulement pour un forfait SANS tacite reconduction, et
        seulement une fois l'abonnement créé chez le fournisseur : la coupure ne
        se déclare pas à l'ouverture de la session, elle se pose sur
        l'abonnement qui en résulte.
        """
        ...
