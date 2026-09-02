"""Ce qu'un canal de vente doit savoir faire, indépendamment du fournisseur.

Deux responsabilités, et deux seulement :

1. **authentifier** ce qui arrive — un webhook est une route ouverte sur
   l'extérieur, la signature est sa seule protection ;
2. **normaliser** — traduire le vocabulaire du fournisseur vers les cinq
   événements du cycle d'abonnement, qui sont ceux du portail.

Ce module est PUR : il ne lit ni base ni réseau. C'est ce qui permet d'écrire et
de vérifier tout le mapping avant qu'un compte de paiement existe.

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

from .subscriptions import SubscriptionEvent


class SignatureInvalide(Exception):
    """La charge utile n'est pas authentifiée. Elle est jetée, pas rejouée.

    Message volontairement pauvre : ce qui remonte au fournisseur ne doit pas
    dire à un attaquant quelle partie de sa contrefaçon a échoué.
    """


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
