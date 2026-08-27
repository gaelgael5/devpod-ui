"""Prix affiche et calcul de taxe (cadrage du 27/08/2026).

Deux regles d'arithmetique y sont figees, et ce sont elles qui se paient cher si
on les rate : montants entiers en unites mineures, et arrondi une seule fois sur
le total. Un flottant ou un double arrondi ne se decouvrent qu'au rapprochement
bancaire.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from portal.billing.models import Offer, OfferPrice, TaxRate
from portal.billing.pricing import (
    PricingError,
    appliquer_taxe,
    devises_manquantes,
    prix_affiche,
    publiable,
    retirer_taxe,
    taux_appliquable,
)

TVA20 = TaxRate(
    country_code="FR",
    rate=Decimal("0.2000"),
    label="TVA 20 %",
    valid_from=date(2014, 1, 1),
)
TVA196 = TaxRate(
    country_code="FR",
    rate=Decimal("0.1960"),
    label="TVA 19,6 %",
    valid_from=date(2000, 1, 1),
    valid_to=date(2014, 1, 1),
)


def _offre(**prix: int) -> Offer:
    return Offer(
        slug="standard",
        prices=[OfferPrice(currency=c, amount_minor=m) for c, m in prix.items()],
    )


# ─── Arrondi ─────────────────────────────────────────────────────────────────


def test_arrondi_commercial_et_non_bancaire() -> None:
    """`ROUND_HALF_UP`, pas le `ROUND_HALF_EVEN` par defaut de Python. Sur une
    demi-valeur exacte, l'arrondi bancaire descendrait vers le pair et
    produirait un centime d'ecart avec le fournisseur de paiement."""
    # 1250 * 1.20 = 1500 pile ; on cherche un cas a .5
    assert appliquer_taxe(125, Decimal("0.20")) == 150
    # 5 * 1.10 = 5.5 -> 6 en commercial, 6 aussi en bancaire (pair) ;
    # 15 * 1.10 = 16.5 -> 17 en commercial, 16 en bancaire. C'est le cas qui tranche.
    assert appliquer_taxe(15, Decimal("0.10")) == 17


def test_aller_retour_ht_ttc_stable_sur_les_cas_courants() -> None:
    for ht in (1000, 999, 2083, 4999):
        ttc = appliquer_taxe(ht, Decimal("0.2000"))
        assert retirer_taxe(ttc, Decimal("0.2000")) == ht


def test_un_montant_negatif_est_refuse() -> None:
    with pytest.raises(PricingError):
        appliquer_taxe(-1, Decimal("0.20"))
    with pytest.raises(PricingError):
        retirer_taxe(-1, Decimal("0.20"))


def test_taux_nul_laisse_le_montant_intact() -> None:
    assert appliquer_taxe(1234, Decimal("0")) == 1234


# ─── Historisation du taux ───────────────────────────────────────────────────


def test_le_taux_retenu_est_celui_de_la_date_d_emission() -> None:
    """Le point structurant : rejouer une facture ancienne doit redonner le meme
    montant, meme si la TVA a change depuis."""
    taux = [TVA20, TVA196]

    assert taux_appliquable(taux, "FR", date(2013, 6, 1)) is TVA196
    assert taux_appliquable(taux, "FR", date(2026, 6, 1)) is TVA20


def test_la_borne_haute_est_exclue() -> None:
    """`valid_to` est la date de FIN : le 01/01/2014 releve deja du taux
    suivant. Sans cette convention, deux taux se chevauchent d'un jour."""
    assert TVA196.couvre(date(2013, 12, 31))
    assert not TVA196.couvre(date(2014, 1, 1))
    assert TVA20.couvre(date(2014, 1, 1))


def test_aucun_taux_avant_le_premier() -> None:
    assert taux_appliquable([TVA20], "FR", date(2010, 1, 1)) is None


def test_un_autre_pays_n_est_pas_servi_par_erreur() -> None:
    assert taux_appliquable([TVA20], "US", date(2026, 6, 1)) is None


def test_le_taux_regional_l_emporte_sur_le_national() -> None:
    """Le plus specifique gagne. La colonne `region` ne sert pas pour la France,
    mais la regle doit tenir avant qu'un pays a taux regionaux arrive."""
    national = TaxRate(
        country_code="XX", rate=Decimal("0.10"), label="national", valid_from=date(2020, 1, 1)
    )
    regional = TaxRate(
        country_code="XX",
        region="CA",
        rate=Decimal("0.15"),
        label="regional",
        valid_from=date(2020, 1, 1),
    )

    assert taux_appliquable([national, regional], "XX", date(2026, 1, 1), region="CA") is regional
    assert taux_appliquable([national, regional], "XX", date(2026, 1, 1), region="NY") is national


# ─── Prix affiche selon le mode de taxe ──────────────────────────────────────


def test_mode_manuel_le_montant_saisi_est_un_ttc() -> None:
    """En manuel, c'est nous qui avons calcule la taxe : le prix stocke est le
    TTC, et le HT s'en deduit pour le detail."""
    p = prix_affiche(_offre(EUR=1200), "EUR", "manuel", [TVA20], "FR", date(2026, 6, 1))

    assert (p.ttc_minor, p.ht_minor) == (1200, 1000)
    assert p.estime is False


def test_mode_automatique_le_montant_saisi_est_un_ht() -> None:
    """En automatique, le provider ajoute la taxe : le TTC affiche n'est qu'une
    estimation, le montant exact est arrete au checkout."""
    p = prix_affiche(_offre(EUR=1000), "EUR", "automatique", [TVA20], "FR", date(2026, 6, 1))

    assert (p.ht_minor, p.ttc_minor) == (1000, 1200)
    assert p.estime is True


def test_manuel_sans_taux_en_vigueur_est_une_erreur() -> None:
    """Sans taux, un prix TTC ne peut pas etre decompose — mieux vaut le dire
    que d'afficher un HT faux."""
    with pytest.raises(PricingError, match="taux"):
        prix_affiche(_offre(EUR=1200), "EUR", "manuel", [], "FR", date(2026, 6, 1))


def test_automatique_sans_taux_local_reste_valide() -> None:
    """C'est le provider qui calcule : l'absence de table locale n'est pas une
    erreur, le montant affiche est simplement le HT."""
    p = prix_affiche(_offre(EUR=1000), "EUR", "automatique", [], "FR", date(2026, 6, 1))

    assert (p.ht_minor, p.ttc_minor, p.estime) == (1000, 1000, True)


# ─── Devise absente : l'offre n'est pas proposee ─────────────────────────────


def test_une_offre_sans_prix_dans_la_devise_n_est_pas_proposee() -> None:
    """Ecarte : le repli sur une devise pivot avec conversion au taux du jour.
    Un taux flottant fait diverger l'affiche du debite."""
    with pytest.raises(PricingError, match="aucun prix en USD"):
        prix_affiche(_offre(EUR=1200), "USD", "manuel", [TVA20], "FR", date(2026, 6, 1))


def test_devises_manquantes_pour_le_garde_fou_de_publication() -> None:
    assert devises_manquantes(_offre(EUR=1200), ["EUR", "USD", "CHF"]) == ["CHF", "USD"]
    assert devises_manquantes(_offre(EUR=1200, USD=1400), ["EUR", "USD"]) == []


def test_publiable_exige_au_moins_une_devise_activee() -> None:
    assert publiable(_offre(EUR=1200), ["EUR", "USD"]) is True
    assert publiable(_offre(GBP=1200), ["EUR", "USD"]) is False


def test_aucune_devise_activee_rend_toute_offre_impubliable() -> None:
    """Aucun pays active : personne ne peut souscrire, publier n'aurait aucun
    sens."""
    assert publiable(_offre(EUR=1200), []) is False
