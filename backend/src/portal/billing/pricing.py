"""Calcul du prix affiché et de la taxe.

Deux règles d'arithmétique, figées au cadrage du 27/08 parce qu'elles se paient
cher plus tard :

1. **Les montants sont des entiers en unités mineures** (centimes). Un flottant
   sur de la facturation produit une erreur silencieuse qui ne se découvre qu'au
   rapprochement bancaire.
2. **L'arrondi se fait une seule fois, sur le total.** Arrondir ligne par ligne
   fait diverger deux chemins de calcul d'un centime, et rend impossible le
   rapprochement avec le fournisseur de paiement.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Offer, TaxMode, TaxRate


class PricingError(Exception):
    """Le prix ne peut pas être établi (FR)."""


def taux_appliquable(
    taux: Iterable[TaxRate],
    country_code: str,
    emission: date,
    region: str = "",
) -> TaxRate | None:
    """Taux en vigueur à la DATE D'ÉMISSION, pas le taux courant.

    C'est ce qui rend une facture ancienne reproductible : rejouer le calcul un
    an plus tard doit redonner le même montant, même si la TVA a changé entre
    temps.

    Un taux régional l'emporte sur le taux national du même pays — le plus
    spécifique gagne.
    """
    candidats = [
        t
        for t in taux
        if t.country_code == country_code and t.region in ("", region) and t.couvre(emission)
    ]
    if not candidats:
        return None
    # `region` non vide en tête : le plus spécifique d'abord.
    candidats.sort(key=lambda t: (t.region == "", t.valid_from), reverse=False)
    candidats.sort(key=lambda t: t.region == "")
    return candidats[0]


def appliquer_taxe(montant_ht_minor: int, taux: Decimal) -> int:
    """HT → TTC, arrondi au centime le plus proche (`ROUND_HALF_UP`).

    `ROUND_HALF_UP` et non le `ROUND_HALF_EVEN` par défaut de Python : c'est la
    règle d'arrondi commercial attendue sur une facture, et celle qu'appliquent
    les fournisseurs de paiement. Le défaut bancaire de Python produirait des
    écarts d'un centime sur les demi-valeurs exactes.
    """
    if montant_ht_minor < 0:
        raise PricingError("montant négatif")
    total = Decimal(montant_ht_minor) * (Decimal(1) + taux)
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def retirer_taxe(montant_ttc_minor: int, taux: Decimal) -> int:
    """TTC → HT. Utile pour afficher le détail d'un prix saisi en TTC."""
    if montant_ttc_minor < 0:
        raise PricingError("montant négatif")
    ht = Decimal(montant_ttc_minor) / (Decimal(1) + taux)
    return int(ht.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class PrixAffiche:
    """Ce qu'on montre à l'utilisateur, et ce qu'on envoie au provider."""

    def __init__(self, ht_minor: int, ttc_minor: int, currency: str, estime: bool) -> None:
        self.ht_minor = ht_minor
        self.ttc_minor = ttc_minor
        self.currency = currency
        # `True` en mode automatique : le montant exact est arrêté par le
        # provider au checkout, celui-ci n'est qu'une estimation.
        self.estime = estime

    def __eq__(self, autre: object) -> bool:
        if not isinstance(autre, PrixAffiche):
            return NotImplemented
        return (self.ht_minor, self.ttc_minor, self.currency, self.estime) == (
            autre.ht_minor,
            autre.ttc_minor,
            autre.currency,
            autre.estime,
        )

    def __repr__(self) -> str:  # pragma: no cover — confort de débogage
        return (
            f"PrixAffiche(ht={self.ht_minor}, ttc={self.ttc_minor}, "
            f"{self.currency}, estime={self.estime})"
        )


def prix_affiche(
    offre: Offer,
    currency: str,
    tax_mode: TaxMode,
    taux: Iterable[TaxRate],
    country_code: str,
    emission: date,
    region: str = "",
) -> PrixAffiche:
    """Prix à montrer pour cette offre, dans cette devise, pour ce pays.

    Le sens du montant stocké dépend du mode de taxe du provider :

    - `manuel` : le montant saisi est un **TTC**, on en déduit le HT pour le
      détail. C'est nous qui avons calculé la taxe.
    - `automatique` : le montant saisi est un **HT**, la taxe est ajoutée par le
      provider. Le TTC affiché n'est alors qu'une **estimation** — le montant
      exact est arrêté au checkout.

    Lève `PricingError` si l'offre n'a pas de prix dans cette devise : une offre
    sans prix n'est pas proposée, plutôt que convertie depuis une devise pivot à
    un taux flottant qui ferait diverger l'affiché du débité.
    """
    prix = offre.prix(currency)
    if prix is None:
        raise PricingError(
            f"offre {offre.slug!r} : aucun prix en {currency} — l'offre n'est pas proposée"
        )

    applicable = taux_appliquable(taux, country_code, emission, region)
    if applicable is None:
        if tax_mode == "manuel":
            raise PricingError(
                f"aucun taux de taxe en vigueur au {emission} pour {country_code!r} : "
                "le prix TTC ne peut pas être décomposé"
            )
        # En automatique, l'absence de taux local n'est pas une erreur : c'est
        # le provider qui calcule.
        return PrixAffiche(prix.amount_minor, prix.amount_minor, currency, estime=True)

    if tax_mode == "manuel":
        return PrixAffiche(
            retirer_taxe(prix.amount_minor, applicable.rate),
            prix.amount_minor,
            currency,
            estime=False,
        )
    return PrixAffiche(
        prix.amount_minor,
        appliquer_taxe(prix.amount_minor, applicable.rate),
        currency,
        estime=True,
    )


def devises_manquantes(offre: Offer, devises_actives: Iterable[str]) -> list[str]:
    """Devises de pays activés pour lesquelles l'offre n'a pas de prix.

    Sert le garde-fou à la publication : une offre sans prix dans une devise
    n'est pas proposée aux utilisateurs de ce pays, et l'absence doit se voir à
    la saisie plutôt que dans une page vide côté client.
    """
    presentes = {p.currency for p in offre.prices}
    return sorted(set(devises_actives) - presentes)


def publiable(offre: Offer, devises_actives: Iterable[str]) -> bool:
    """Une offre sans prix dans AUCUNE devise activée n'est proposable à personne."""
    actives = set(devises_actives)
    if not actives:
        return False
    return any(p.currency in actives for p in offre.prices)
