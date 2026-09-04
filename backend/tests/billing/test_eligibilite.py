"""Qui a le droit de souscrire, et pourquoi on refuse.

Ce module est PUR : aucune base, aucun fournisseur de paiement. C'est ce qui
permet d'y épingler des règles commerciales sans monter d'infrastructure.

Le test qui compte le plus est celui qui vérifie qu'une offre RÉPÉTABLE le reste :
c'est le cas qu'une clé d'idempotence trop large avait déjà interdit en silence.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.billing.eligibilite import SouscriptionRefusee, verifier
from portal.billing.models import Offer, OfferPrice


def _offre(**extra: Any) -> Offer:
    base: dict[str, Any] = {
        "slug": "standard",
        "label": "Standard",
        "hosting_type": "mutualise",
        "published": True,
        "duration_days": 30,
        "provider_slug": "stripe-fr",
        "prices": [OfferPrice(currency="EUR", amount_minor=1200)],
    }
    base.update(extra)
    return Offer.model_validate(base)


def _verifier(offre: Offer, **extra: Any) -> None:
    args: dict[str, Any] = {
        "offres_deja_souscrites": set(),
        "devise": "EUR",
        "devises_actives": {"EUR", "USD"},
        "providers_du_pays": {"stripe-fr"},
        "pays": "FR",
    }
    args.update(extra)
    verifier(offre, **args)


def test_le_cas_nominal_passe() -> None:
    _verifier(_offre())


def test_une_offre_repetable_peut_etre_reprise() -> None:
    """LE test de non-régression : prendre deux fois le même forfait est légitime.

    Rien ne justifie de l'interdire, et une clé d'idempotence trop large l'avait
    déjà fait — la seconde souscription ne recevait rien, sans message.
    """
    _verifier(_offre(une_par_compte=False), offres_deja_souscrites={"standard"})


def test_une_offre_unique_ne_se_reprend_pas() -> None:
    with pytest.raises(SouscriptionRefusee, match="une par compte"):
        _verifier(_offre(une_par_compte=True), offres_deja_souscrites={"standard"})


def test_une_offre_unique_reste_souscriptible_la_premiere_fois() -> None:
    _verifier(_offre(une_par_compte=True), offres_deja_souscrites={"autre"})


def test_une_offre_non_publiee_est_refusee() -> None:
    """Brouillon ou offre retirée du catalogue : elle ne se vend pas.

    La deviner par son slug ne doit pas suffire à la souscrire.
    """
    with pytest.raises(SouscriptionRefusee, match="plus proposée"):
        _verifier(_offre(published=False))


def test_une_offre_sans_duree_est_refusee() -> None:
    """Sans terme, l'échéance ne se calcule pas et l'abonnement ne finirait jamais.

    Le garde-fou de publication l'exige déjà — on ne s'y fie pas seule.
    """
    with pytest.raises(SouscriptionRefusee, match="durée"):
        _verifier(_offre(duration_days=None))


def test_une_devise_non_acceptee_est_refusee() -> None:
    with pytest.raises(SouscriptionRefusee, match="GBP"):
        _verifier(_offre(), devise="GBP")


def test_une_offre_sans_prix_dans_la_devise_choisie_est_refusee() -> None:
    """Pas de conversion : un taux flottant ferait diverger l'affiché du débité."""
    with pytest.raises(SouscriptionRefusee, match="prix en USD"):
        _verifier(_offre(), devise="USD")


def test_un_canal_indisponible_dans_le_pays_est_refuse() -> None:
    """Refus assumé comme provisoire : le client n'y peut rien.

    C'est un trou de configuration, et le message ne l'accuse pas.
    """
    with pytest.raises(SouscriptionRefusee, match="pays BE"):
        _verifier(_offre(), providers_du_pays=set(), pays="BE")


def test_un_canal_indisponible_porte_sa_propre_exception() -> None:
    """`CanalIndisponible` reste une `SouscriptionRefusee` — même refus pour le
    client — mais l'appelant peut la reconnaître : c'est une VENTE PERDUE sur un
    trou de configuration, et l'exploitant doit le savoir (DoD du ticket « Pays
    sans canal de paiement »)."""
    from portal.billing.eligibilite import CanalIndisponible

    with pytest.raises(CanalIndisponible):
        _verifier(_offre(), providers_du_pays=set(), pays="BE")


def test_une_offre_sans_canal_de_paiement_est_refusee() -> None:
    with pytest.raises(SouscriptionRefusee, match="canal de paiement"):
        _verifier(_offre(provider_slug=None))


# ─── L'offre gratuite ne passe par aucun de ces contrôles ────────────────────


def test_une_offre_gratuite_n_a_besoin_ni_de_prix_ni_de_canal() -> None:
    """Elle n'a rien à encaisser : exiger un prix ou un canal la refuserait.

    C'est le seul parcours exerçable de bout en bout tant qu'aucun compte de
    paiement n'existe.
    """
    _verifier(_offre(is_free=True, prices=[], provider_slug=None), providers_du_pays=set())


def test_une_offre_gratuite_reste_bornee_par_une_par_compte() -> None:
    """La gratuité n'exempte pas de la règle d'unicité — c'est même son usage."""
    with pytest.raises(SouscriptionRefusee, match="une par compte"):
        _verifier(
            _offre(is_free=True, prices=[], une_par_compte=True),
            offres_deja_souscrites={"standard"},
        )


def test_une_offre_gratuite_reste_soumise_a_la_publication() -> None:
    with pytest.raises(SouscriptionRefusee, match="plus proposée"):
        _verifier(_offre(is_free=True, prices=[], published=False))
