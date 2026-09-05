"""Tests de l'état des abonnements et de l'idempotence des webhooks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from portal.billing.config import PolitiqueRelance
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
    fin_de_forfait,
    relance_due,
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
    """Chaque kind vit dans exactement UNE des deux tables : transition décidée
    (ETAT_APRES) ou journalisation sans transition (KINDS_SANS_TRANSITION,
    arbitrage produit ouvert). Ajouter un kind sans le classer casse ici."""
    from typing import get_args

    from portal.billing.subscriptions import KINDS_SANS_TRANSITION, EventKind

    assert set(ETAT_APRES) == {
        "debut_essai",
        "activation",
        "renouvellement",
        "echec_paiement",
        "resiliation",
    }
    assert set(ETAT_APRES) | KINDS_SANS_TRANSITION == set(get_args(EventKind))
    assert not set(ETAT_APRES) & KINDS_SANS_TRANSITION


def test_un_evenement_informatif_ne_s_applique_jamais() -> None:
    """Journalisé, pas appliqué : l'appliquer serait une faute de programmation
    — un effet d'état sur une politique non tranchée."""
    from datetime import UTC, datetime

    import pytest as _pytest

    from portal.billing.subscriptions import Subscription, SubscriptionEvent, appliquer

    sub = Subscription.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "login": "alice",
            "offer_slug": "standard",
            "state": "actif",
            "country_code": "FR",
            "currency": "EUR",
            "amount_minor": 1200,
        }
    )
    for kind in ("remboursement", "litige_ouvert", "litige_clos"):
        evt = SubscriptionEvent(kind=kind, provider_slug="stripe-fr", provider_event_id="evt_x")
        with _pytest.raises(ValueError, match="journalisé"):
            appliquer(sub, evt, datetime.now(UTC))


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


# --- Relance d'un prélèvement refusé ---------------------------------------
#
# Un refus est souvent passager : plafond mensuel, carte expirée du matin.
# On relance une fois, puis on coupe — et couper veut dire résilier, donc de
# façon réversible.

RELANCE = PolitiqueRelance(delai_heures=6, tentatives_max=2)


def test_le_premier_refus_ne_coupe_pas_le_service() -> None:
    maj = appliquer(_sub(state="actif"), _event("echec_paiement"), T1, RELANCE)
    assert maj.state == "echec_paiement"
    assert maj.ouvert is True


def test_le_premier_refus_programme_une_relance_au_delai_configure() -> None:
    maj = appliquer(_sub(state="actif"), _event("echec_paiement"), T1, RELANCE)
    assert maj.payment_attempts == 1
    assert maj.next_retry_at == T1 + timedelta(hours=6)


def test_le_delai_de_relance_est_parametrable() -> None:
    maj = appliquer(
        _sub(state="actif"),
        _event("echec_paiement"),
        T1,
        PolitiqueRelance(delai_heures=48),
    )
    assert maj.next_retry_at == T1 + timedelta(hours=48)


def test_le_second_refus_coupe() -> None:
    # Deuxième essai raté : on résilie. Réversible — le compte demeure.
    sub = _sub(state="echec_paiement", payment_attempts=1, next_retry_at=T0)
    maj = appliquer(sub, _event("echec_paiement", "evt_2"), T1, RELANCE)
    assert maj.state == "resilie"
    assert maj.ouvert is False
    assert maj.next_retry_at is None


def test_couper_laisse_la_reprise_ouverte() -> None:
    coupe = appliquer(
        _sub(state="echec_paiement", payment_attempts=1),
        _event("echec_paiement", "evt_2"),
        T1,
        RELANCE,
    )
    repris = reprendre(coupe, currency="EUR", amount_minor=2900, moment=T1)
    assert repris.ouvert is True


def test_le_nombre_de_tentatives_est_parametrable() -> None:
    politique = PolitiqueRelance(delai_heures=6, tentatives_max=3)
    sub = _sub(state="echec_paiement", payment_attempts=1)
    maj = appliquer(sub, _event("echec_paiement", "evt_2"), T1, politique)
    assert maj.state == "echec_paiement"  # une relance de plus avant de couper
    assert maj.payment_attempts == 2


def test_une_seule_tentative_coupe_des_le_premier_refus() -> None:
    politique = PolitiqueRelance(tentatives_max=1)
    maj = appliquer(_sub(state="actif"), _event("echec_paiement"), T1, politique)
    assert maj.state == "resilie"


def test_un_paiement_reussi_solde_l_episode_d_echec() -> None:
    # Sinon un refus isolé six mois plus tard couperait aussitôt.
    sub = _sub(state="echec_paiement", payment_attempts=1, next_retry_at=T1)
    maj = appliquer(sub, _event("renouvellement"), T1, RELANCE)
    assert maj.state == "actif"
    assert maj.payment_attempts == 0
    assert maj.next_retry_at is None


def test_la_relance_est_due_a_l_echeance() -> None:
    sub = _sub(state="echec_paiement", payment_attempts=1, next_retry_at=T0)
    assert relance_due(sub, T1) is True


def test_la_relance_n_est_pas_due_avant_l_echeance() -> None:
    sub = _sub(state="echec_paiement", payment_attempts=1, next_retry_at=T1)
    assert relance_due(sub, T0) is False


def test_un_abonnement_coupe_n_est_plus_relance() -> None:
    # Distingue « en attente de relance » de « coupé » : sans relance
    # programmée, le scheduler passe son chemin.
    assert relance_due(_sub(state="resilie", next_retry_at=None), T1) is False


def test_un_abonnement_sain_n_est_jamais_relance() -> None:
    assert relance_due(_sub(state="actif"), T1) is False


def test_la_reprise_repart_d_une_ardoise_nette() -> None:
    # Sinon les échecs de l'abonnement clos couperaient la reprise au 1er refus.
    coupe = _sub(state="resilie", payment_attempts=2, next_retry_at=T0)
    repris = reprendre(coupe, currency="EUR", amount_minor=2900, moment=T1)
    assert repris.payment_attempts == 0
    assert repris.next_retry_at is None


# ─── Fin de forfait : tout forfait est borné dans le temps ────────────────────


def test_fin_de_forfait_ajoute_les_jours_au_depart():
    debut = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)

    assert fin_de_forfait(debut, 30) == datetime(2026, 2, 14, 9, 30, tzinfo=UTC)


def test_fin_de_forfait_traverse_un_changement_d_annee():
    """L'arithmétique de calendrier n'est pas de l'arithmétique de 365 jours."""
    debut = datetime(2026, 12, 20, tzinfo=UTC)

    assert fin_de_forfait(debut, 30) == datetime(2027, 1, 19, tzinfo=UTC)


def test_fin_de_forfait_refuse_une_duree_nulle():
    """Un forfait de zéro jour finirait avant d'avoir commencé."""
    with pytest.raises(ValueError):
        fin_de_forfait(datetime(2026, 1, 1, tzinfo=UTC), 0)


def test_reprise_repart_pour_un_terme_neuf():
    """Une reprise est un acte commercial NEUF : le terme se recalcule.

    Reconduire l'ancienne date rouvrirait un abonnement déjà expiré.
    """
    moment = datetime(2026, 6, 1, tzinfo=UTC)
    sub = _sub(state="resilie", ends_at=datetime(2026, 1, 1, tzinfo=UTC))

    repris = reprendre(sub, currency="EUR", amount_minor=1200, moment=moment, duration_days=30)

    assert repris.ends_at == datetime(2026, 7, 1, tzinfo=UTC)


def test_reprise_sans_duree_ne_pose_pas_de_terme():
    """Sans durée fournie, on ne devine pas : le terme reste à poser."""
    sub = _sub(state="resilie", ends_at=datetime(2026, 1, 1, tzinfo=UTC))

    repris = reprendre(
        sub, currency="EUR", amount_minor=1200, moment=datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert repris.ends_at is None


def test_l_echeance_garde_l_heure_de_souscription():
    """Arrondir au jour offrirait jusqu'a 24 h de service a chaque souscription.

    Et ferait echoir tous les abonnements a la meme seconde, ce qui concentre
    les renouvellements au lieu de les etaler.
    """
    debut = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)

    echeance = fin_de_forfait(debut, 30)

    assert (echeance.hour, echeance.minute) == (9, 30)


def test_l_echeance_ne_descend_pas_sous_la_minute():
    """Les secondes datent de l'arrivee du webhook, pas d'une decision commerciale."""
    debut = datetime(2026, 1, 15, 9, 30, 47, 123456, tzinfo=UTC)

    echeance = fin_de_forfait(debut, 30)

    assert echeance == datetime(2026, 2, 14, 9, 30, tzinfo=UTC)


def test_deux_souscriptions_de_la_meme_minute_echoient_ensemble():
    """Sinon deux abonnes de la meme minute renouvellent a des instants differents."""
    a = fin_de_forfait(datetime(2026, 3, 1, 14, 5, 3, tzinfo=UTC), 7)
    b = fin_de_forfait(datetime(2026, 3, 1, 14, 5, 58, tzinfo=UTC), 7)

    assert a == b
