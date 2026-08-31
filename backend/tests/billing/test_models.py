"""Modeles du socle des forfaits : ce que le schema refuse d'enregistrer.

L'interet de ces tests n'est pas de verifier pydantic, mais de figer les regles
qui ont ete tranchees au cadrage — notamment celles dont l'oubli ne se verrait
qu'en production.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from portal.billing.models import (
    Country,
    Currency,
    Offer,
    OfferPrice,
    PaymentProvider,
    StripeConfig,
    TaxRate,
)

# ─── Provider : aucun secret, et `kind` distinct de `slug` ───────────────────


def test_le_provider_ne_porte_qu_une_reference_de_secret() -> None:
    """La cle API vit dans la table des secrets. Le modele n'a aucun champ pour
    l'accueillir — c'est structurel, pas une convention."""
    champs = set(PaymentProvider.model_fields)

    assert "secret_slug" in champs
    for interdit in ("api_key", "secret", "secret_key", "token", "password"):
        assert interdit not in champs


def test_deux_instances_du_meme_kind_coexistent() -> None:
    """Test et production, ou deux entites juridiques : le slug identifie
    l'instance, le kind dit quel adaptateur la pilote."""
    test = PaymentProvider(slug="stripe-test", kind="stripe", label="Stripe (test)")
    prod = PaymentProvider(slug="stripe-eu", kind="stripe", label="Stripe (EU)")

    assert test.slug != prod.slug
    assert test.kind == prod.kind == "stripe"


def test_une_config_hors_schema_du_kind_est_refusee() -> None:
    """`extra=forbid` sur StripeConfig : une cle inconnue est refusee A LA
    SAISIE, pas decouverte au premier paiement."""
    with pytest.raises(ValidationError):
        PaymentProvider(
            slug="stripe-eu", kind="stripe", label="Stripe", config={"acount_id": "acct_1"}
        )


def test_une_config_conforme_est_acceptee() -> None:
    p = PaymentProvider(
        slug="stripe-eu",
        kind="stripe",
        label="Stripe",
        config={"account_id": "acct_1", "webhook_secret_slug": "stripe.whsec"},
    )
    assert p.config["account_id"] == "acct_1"


def test_stripe_config_ne_porte_pas_le_secret_de_webhook_mais_sa_reference() -> None:
    champs = set(StripeConfig.model_fields)

    assert "webhook_secret_slug" in champs
    assert "webhook_secret" not in champs


def test_mode_de_taxe_borne() -> None:
    with pytest.raises(ValidationError):
        PaymentProvider(slug="s", kind="stripe", label="S", tax_mode="approximatif")


# ─── Pays et devises : codes normalises ──────────────────────────────────────


def test_code_pays_iso_deux_lettres_majuscules() -> None:
    assert Country(code="FR", label="France").code == "FR"
    for mauvais in ("fr", "FRA", "F", "F1"):
        with pytest.raises(ValidationError):
            Country(code=mauvais, label="x")


def test_devise_iso_trois_lettres_majuscules() -> None:
    assert Currency(code="EUR").code == "EUR"
    for mauvais in ("eur", "EU", "EURO"):
        with pytest.raises(ValidationError):
            Currency(code=mauvais)


# ─── Taux : historisation ────────────────────────────────────────────────────


def test_une_periode_inversee_est_refusee() -> None:
    with pytest.raises(ValidationError):
        TaxRate(
            country_code="FR",
            rate=Decimal("0.2"),
            label="x",
            valid_from=date(2026, 1, 1),
            valid_to=date(2025, 1, 1),
        )


def test_un_taux_negatif_est_refuse() -> None:
    with pytest.raises(ValidationError):
        TaxRate(country_code="FR", rate=Decimal("-0.2"), label="x", valid_from=date(2026, 1, 1))


def test_sans_valid_to_le_taux_est_en_vigueur() -> None:
    t = TaxRate(country_code="FR", rate=Decimal("0.2"), label="x", valid_from=date(2014, 1, 1))

    assert t.couvre(date(2099, 1, 1))


# ─── Offre : quotas et prix ──────────────────────────────────────────────────


def test_quota_nul_signifie_illimite_pas_zero() -> None:
    """`None` = illimite. `0` n'a pas de sens — une offre a zero workspace ne se
    vend pas — et le laisser passer donnerait un forfait inutilisable en
    silence."""
    assert Offer(slug="free").max_workspaces is None

    with pytest.raises(ValidationError):
        Offer(slug="free", max_workspaces=0)


def test_les_deux_quotas_sont_independants() -> None:
    o = Offer(slug="max", max_workspaces=10, max_hosts_dedies=None)

    assert o.max_workspaces == 10
    assert o.max_hosts_dedies is None


def test_deux_prix_dans_la_meme_devise_sont_refuses() -> None:
    """Sinon le choix du prix a la souscription serait non deterministe."""
    with pytest.raises(ValidationError, match="EUR"):
        Offer(
            slug="standard",
            prices=[
                OfferPrice(currency="EUR", amount_minor=1000),
                OfferPrice(currency="EUR", amount_minor=1200),
            ],
        )


def test_un_prix_negatif_est_refuse() -> None:
    with pytest.raises(ValidationError):
        OfferPrice(currency="EUR", amount_minor=-1)


def test_le_type_d_hebergement_est_borne() -> None:
    with pytest.raises(ValidationError):
        Offer(slug="x", hosting_type="cloud")


def test_une_offre_est_non_publiee_par_defaut() -> None:
    """Une offre en cours de saisie ne doit etre proposee a personne."""
    assert Offer(slug="brouillon").published is False


def test_prix_ht_par_defaut() -> None:
    """Le sens du montant est explicite, et prudent par defaut : HT.

    Le deduire du mode de taxe du canal etait fragile — une offre peut changer
    de canal sans que ses prix changent de nature.
    """
    assert Offer(slug="std").prices_include_tax is False


def test_majoration_par_defaut_neutre() -> None:
    assert Offer(slug="std").currency_markup == Decimal("1")
    assert Offer(slug="std").auto_currencies is False


def test_majoration_nulle_ou_negative_refusee() -> None:
    # Une majoration a zero rendrait l'offre gratuite dans toutes les devises
    # derivees, sans que personne ne l'ait voulu.
    for mauvais in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            Offer(slug="std", currency_markup=mauvais)


def test_offre_gratuite_avec_un_prix_est_refusee():
    """Gratuit ET tarifé n'a pas de sens : l'un des deux serait applique au hasard."""
    with pytest.raises(ValidationError):
        Offer(
            slug="bienvenue",
            is_free=True,
            duration_days=30,
            prices=[OfferPrice(currency="EUR", amount_minor=1200)],
        )


def test_duree_nulle_ou_negative_refusee():
    with pytest.raises(ValidationError):
        Offer(slug="standard", duration_days=0)


# ─── Profils de host : ce que l'offre sait provisionner ───────────────────────


def test_les_profils_de_host_sont_ordonnes_par_priorite():
    """L'ordre EST la priorité : le premier est celui qu'on essaie d'abord.

    Un ensemble non ordonné aurait obligé à porter un rang à part, qui se
    désynchronise de la liste au premier retrait.
    """
    offre = Offer(slug="standard", host_profiles=["gros", "petit"])

    assert offre.host_profiles == ["gros", "petit"]


def test_un_profil_de_host_ne_peut_pas_figurer_deux_fois():
    """Deux fois le même profil ne dit rien de plus, et rend la priorité
    ambiguë : lequel des deux rangs compte ?"""
    with pytest.raises(ValidationError, match="deux fois"):
        Offer(slug="standard", host_profiles=["gros", "gros"])


def test_un_slug_de_profil_de_host_est_valide_comme_les_autres():
    with pytest.raises(ValidationError, match="invalide"):
        Offer(slug="standard", host_profiles=["Gros Profil"])


def test_une_offre_sans_profil_de_host_reste_saisissable():
    """La liste vide est un brouillon, pas une erreur — c'est la PUBLICATION
    qui exige un profil, comme elle exige déjà une durée et un prix."""
    assert Offer(slug="standard").host_profiles == []
