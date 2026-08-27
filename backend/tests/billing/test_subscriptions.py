"""Tests de l'état des abonnements et de l'idempotence des webhooks."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from portal.billing.subscriptions import (
    ETAT_APRES,
    RepriseRefusee,
    Subscription,
    SubscriptionEvent,
    TransitionRefusee,
    appliquer,
    cle_idempotence,
    deja_traite,
    etat_apres,
    reprendre,
)

T0 = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)


def _sub(**kw: object) -> Subscription:
    base: dict[str, object] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "login": "alice",
        "offer_slug": "pro",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 2900,
    }
    base.update(kw)
    return Subscription(**base)  # type: ignore[arg-type]


def _event(kind: str = "activation", event_id: str = "evt_1") -> SubscriptionEvent:
    return SubscriptionEvent(
        kind=kind,  # type: ignore[arg-type]
        provider_slug="stripe-prod",
        provider_event_id=event_id,
    )


# --- Modèle d'abonnement ---------------------------------------------------


def test_la_devise_hors_iso4217_est_refusee() -> None:
    with pytest.raises(ValidationError, match="ISO-4217"):
        _sub(currency="eur")


def test_le_code_pays_invalide_est_refuse() -> None:
    with pytest.raises(ValidationError, match="ISO-3166"):
        _sub(country_code="FRA")


def test_un_montant_negatif_est_refuse() -> None:
    with pytest.raises(ValidationError):
        _sub(amount_minor=-1)


def test_l_abonnement_porte_le_prix_souscrit_en_instantane() -> None:
    # Le catalogue peut bouger : l'abonnement porte son propre montant.
    sub = _sub(amount_minor=1900)
    assert sub.amount_minor == 1900
    assert sub.currency == "EUR"


@pytest.mark.parametrize("etat", ["essai", "actif", "echec_paiement"])
def test_le_service_reste_ouvert_tant_que_non_resilie(etat: str) -> None:
    # `echec_paiement` reste ouvert : c'est la période de grâce.
    assert _sub(state=etat).ouvert is True


def test_le_service_est_ferme_une_fois_resilie() -> None:
    assert _sub(state="resilie").ouvert is False


# --- Transitions d'état ----------------------------------------------------


def test_tous_les_types_d_evenement_ont_un_effet_declare() -> None:
    # Ajouter un événement sans décider de son effet doit casser ici.
    assert set(ETAT_APRES) == {
        "debut_essai",
        "activation",
        "renouvellement",
        "echec_paiement",
        "resiliation",
    }


def test_le_paiement_active_l_abonnement() -> None:
    assert etat_apres("essai", "activation") == "actif"


def test_un_prelevement_refuse_bascule_en_echec_de_paiement() -> None:
    assert etat_apres("actif", "echec_paiement") == "echec_paiement"


def test_un_renouvellement_rattrape_un_echec_de_paiement() -> None:
    assert etat_apres("echec_paiement", "renouvellement") == "actif"


def test_un_webhook_en_retard_ne_rouvre_pas_un_abonnement_resilie() -> None:
    # Livré après la résiliation qu'il précède : sans cette garde, il rouvrirait
    # le service tout seul, au tarif d'hier. La reprise a sa propre porte.
    with pytest.raises(TransitionRefusee, match="reprendre"):
        etat_apres("resilie", "renouvellement")


def test_le_changement_d_etat_est_horodate() -> None:
    maj = appliquer(_sub(state="essai", state_changed_at=T0), _event("activation"), T1)
    assert maj.state == "actif"
    assert maj.state_changed_at == T1


def test_l_horodatage_avance_meme_sans_changement_d_etat() -> None:
    # Renouvellement d'un abonnement déjà actif : le scheduler de rétention se
    # sert de cette date, elle doit refléter le dernier signe de vie.
    maj = appliquer(_sub(state="actif", state_changed_at=T0), _event("renouvellement"), T1)
    assert maj.state == "actif"
    assert maj.state_changed_at == T1


def test_appliquer_ne_mute_pas_l_abonnement_d_origine() -> None:
    sub = _sub(state="essai")
    appliquer(sub, _event("activation"), T1)
    assert sub.state == "essai"


# --- Idempotence des webhooks ----------------------------------------------


def test_un_evenement_sans_identifiant_est_refuse() -> None:
    with pytest.raises(ValidationError, match="idempotence"):
        SubscriptionEvent(kind="activation", provider_slug="stripe-prod", provider_event_id="  ")


def test_la_clef_porte_le_couple_provider_et_evenement() -> None:
    assert cle_idempotence(_event(event_id="evt_9")) == ("stripe-prod", "evt_9")


def test_un_evenement_deja_vu_est_ignore() -> None:
    assert deja_traite(_event(event_id="evt_1"), {("stripe-prod", "evt_1")}) is True


def test_un_evenement_neuf_est_traite() -> None:
    assert deja_traite(_event(event_id="evt_2"), {("stripe-prod", "evt_1")}) is False


def test_deux_providers_ne_se_confondent_pas_sur_le_meme_identifiant() -> None:
    # Les identifiants d'événement ne sont uniques que par fournisseur.
    autre = SubscriptionEvent(
        kind="activation", provider_slug="stripe-test", provider_event_id="evt_1"
    )
    assert deja_traite(autre, {("stripe-prod", "evt_1")}) is False


# --- Reprise après résiliation ---------------------------------------------
#
# Une résiliation n'est pas une suppression de compte : elle arrête
# l'abonnement, le compte demeure, et l'utilisateur peut revenir.


def test_un_abonnement_resilie_se_reprend() -> None:
    repris = reprendre(
        _sub(state="resilie", state_changed_at=T0),
        currency="EUR",
        amount_minor=3900,
        moment=T1,
    )
    assert repris.state == "actif"
    assert repris.state_changed_at == T1


def test_la_reprise_refige_le_prix_au_tarif_du_jour() -> None:
    # L'instantané protégeait l'abonné pendant la vie de son abonnement ; il ne
    # lui garantit pas un tarif d'archive à la reprise.
    repris = reprendre(
        _sub(state="resilie", amount_minor=2900),
        currency="EUR",
        amount_minor=3900,
        moment=T1,
    )
    assert repris.amount_minor == 3900


def test_la_reprise_oublie_l_abonnement_mort_chez_le_fournisseur() -> None:
    # Garder l'ancien identifiant ferait router les webhooks de la reprise vers
    # un objet clos côté fournisseur.
    repris = reprendre(
        _sub(state="resilie", provider_subscription_id="sub_ancien"),
        currency="EUR",
        amount_minor=2900,
        moment=T1,
    )
    assert repris.provider_subscription_id == ""


def test_la_reprise_peut_changer_d_offre() -> None:
    repris = reprendre(
        _sub(state="resilie", offer_slug="pro"),
        currency="EUR",
        amount_minor=900,
        moment=T1,
        offer_slug="starter",
    )
    assert repris.offer_slug == "starter"


def test_la_reprise_peut_repasser_par_un_essai() -> None:
    repris = reprendre(
        _sub(state="resilie"),
        currency="EUR",
        amount_minor=2900,
        moment=T1,
        en_essai=True,
    )
    assert repris.state == "essai"


def test_le_service_reprend_apres_une_reprise() -> None:
    sub = _sub(state="resilie")
    assert sub.ouvert is False
    assert reprendre(sub, currency="EUR", amount_minor=2900, moment=T1).ouvert is True


@pytest.mark.parametrize("etat", ["essai", "actif", "echec_paiement"])
def test_il_n_y_a_rien_a_reprendre_sur_un_abonnement_vivant(etat: str) -> None:
    with pytest.raises(RepriseRefusee, match="pas résilié"):
        reprendre(_sub(state=etat), currency="EUR", amount_minor=2900, moment=T1)


def test_la_reprise_ne_mute_pas_l_abonnement_d_origine() -> None:
    sub = _sub(state="resilie", amount_minor=2900)
    reprendre(sub, currency="EUR", amount_minor=3900, moment=T1)
    assert sub.state == "resilie"
    assert sub.amount_minor == 2900
