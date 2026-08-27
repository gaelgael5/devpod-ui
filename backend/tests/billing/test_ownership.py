"""Tests de la propriété des machines et du quota de workspaces.

Le point vérifié en priorité : la CAPACITÉ DE LA MACHINE prime sur tout. Ce
n'est pas une règle commerciale mais une limite physique — le nombre de
workspaces qui peuvent tourner sans planter. Aucun forfait ne la relève.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from portal.billing.ownership import (
    HostGuest,
    HostOwnership,
    QuotaDepasse,
    capacite_restante,
    invitation_valide,
    limite_effective,
    logins_autorises,
    nouveau_token,
    places_pour,
    verifier_creation,
)

MAINTENANT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
HIER = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
DEMAIN = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _ownership(**kw: object) -> HostOwnership:
    base: dict[str, object] = {
        "host_name": "vm-alice",
        "owner_login": "alice",
        "capacity_workspaces": 5,
    }
    base.update(kw)
    return HostOwnership(**base)  # type: ignore[arg-type]


def _guest(login: str = "bob", **kw: object) -> HostGuest:
    base: dict[str, object] = {
        "host_name": "vm-alice",
        "email": f"{login}@example.org",
        "login": login,
        "state": "accepte",
    }
    base.update(kw)
    return HostGuest(**base)  # type: ignore[arg-type]


# --- Modèles ---------------------------------------------------------------


def test_une_adresse_invalide_est_refusee() -> None:
    with pytest.raises(ValidationError, match="email invalide"):
        HostGuest(host_name="vm-alice", email="pas-une-adresse")


def test_l_adresse_est_normalisee_en_minuscules() -> None:
    guest = HostGuest(host_name="vm-alice", email="  Bob@Example.ORG ")
    assert guest.email == "bob@example.org"


def test_une_invitation_non_acceptee_ne_donne_pas_acces() -> None:
    # On invite une adresse : tant qu'elle n'a pas accepté, aucun droit.
    assert _guest(state="invite", login=None).actif is False


def test_une_invitation_revoquee_ne_donne_plus_acces() -> None:
    assert _guest(state="revoque").actif is False


def test_une_allocation_nulle_est_refusee() -> None:
    # Allouer zéro place à un invité, c'est ne pas l'inviter.
    with pytest.raises(ValidationError):
        _guest(allocated_workspaces=0)


def test_le_jeton_d_invitation_est_indevinable_et_unique() -> None:
    a, b = nouveau_token(), nouveau_token()
    assert a != b
    assert len(a) >= 40


def test_une_invitation_expiree_n_est_plus_valide() -> None:
    assert invitation_valide(_guest(state="invite", expires_at=HIER), MAINTENANT) is False


def test_une_invitation_dans_les_temps_est_valide() -> None:
    assert invitation_valide(_guest(state="invite", expires_at=DEMAIN), MAINTENANT) is True


def test_une_invitation_sans_echeance_ne_expire_pas() -> None:
    assert invitation_valide(_guest(state="invite"), MAINTENANT) is True


def test_une_invitation_deja_acceptee_n_est_plus_a_accepter() -> None:
    assert invitation_valide(_guest(state="accepte"), MAINTENANT) is False


# --- Capacité de la machine ------------------------------------------------


def test_la_capacite_restante_se_calcule_sur_le_total_de_la_machine() -> None:
    assert capacite_restante(_ownership(capacity_workspaces=5), 3) == 2


def test_la_capacite_restante_ne_devient_jamais_negative() -> None:
    assert capacite_restante(_ownership(capacity_workspaces=5), 7) == 0


def test_une_capacite_absente_signifie_illimitee() -> None:
    assert capacite_restante(_ownership(capacity_workspaces=None), 42) is None


def test_les_autorises_sont_le_proprietaire_et_les_invites_acceptes() -> None:
    guests = [_guest("bob"), _guest("carol", state="invite"), _guest("dave", state="revoque")]
    assert logins_autorises(_ownership(), guests) == {"alice", "bob"}


# --- Décision de création --------------------------------------------------


def test_un_inconnu_ne_peut_pas_poser_de_workspace() -> None:
    with pytest.raises(QuotaDepasse, match="ni propriétaire ni invité"):
        verifier_creation(_ownership(), [], {}, "mallory")


def test_le_proprietaire_cree_dans_la_capacite_restante() -> None:
    verifier_creation(_ownership(capacity_workspaces=5), [], {"alice": 4}, "alice")


def test_la_capacite_de_la_machine_est_partagee_avec_les_invites() -> None:
    # Le cœur du modèle : 5 places au total, l'owner en a 3, bob 2 → plus rien,
    # y compris pour le propriétaire.
    with pytest.raises(QuotaDepasse, match="capacité de la machine"):
        verifier_creation(
            _ownership(capacity_workspaces=5), [_guest("bob")], {"alice": 3, "bob": 2}, "alice"
        )


def test_un_invite_est_borne_par_sa_sous_allocation() -> None:
    with pytest.raises(QuotaDepasse, match="allocation de bob"):
        verifier_creation(
            _ownership(capacity_workspaces=5),
            [_guest("bob", allocated_workspaces=2)],
            {"alice": 1, "bob": 2},
            "bob",
        )


def test_un_invite_sans_sous_allocation_consomme_le_reste() -> None:
    verifier_creation(
        _ownership(capacity_workspaces=5), [_guest("bob")], {"alice": 1, "bob": 3}, "bob"
    )


def test_la_capacite_machine_prime_sur_l_allocation_de_l_invite() -> None:
    # bob a droit à 4 places mais la machine est pleine : c'est la limite
    # physique payée qui l'emporte.
    with pytest.raises(QuotaDepasse, match="capacité de la machine"):
        verifier_creation(
            _ownership(capacity_workspaces=3),
            [_guest("bob", allocated_workspaces=4)],
            {"alice": 2, "bob": 1},
            "bob",
        )


def test_une_machine_illimitee_n_oppose_aucun_quota() -> None:
    verifier_creation(_ownership(capacity_workspaces=None), [], {"alice": 99}, "alice")


# --- Places restantes, pour l'affichage ------------------------------------


def test_les_places_d_un_inconnu_sont_nulles() -> None:
    assert places_pour(_ownership(), [], {}, "mallory") == 0


def test_les_places_du_proprietaire_sont_le_reste_de_la_machine() -> None:
    assert (
        places_pour(
            _ownership(capacity_workspaces=5), [_guest("bob")], {"alice": 1, "bob": 2}, "alice"
        )
        == 2
    )


def test_les_places_d_un_invite_sont_le_minimum_des_deux_limites() -> None:
    places = places_pour(
        _ownership(capacity_workspaces=5),
        [_guest("bob", allocated_workspaces=4)],
        {"alice": 3, "bob": 0},
        "bob",
    )
    assert places == 2  # 2 restantes sur la machine, 4 allouées à bob


def test_les_places_sont_illimitees_sans_capacite_ni_allocation() -> None:
    assert places_pour(_ownership(capacity_workspaces=None), [_guest("bob")], {}, "bob") is None


def test_une_allocation_borne_meme_une_machine_illimitee() -> None:
    places = places_pour(
        _ownership(capacity_workspaces=None),
        [_guest("bob", allocated_workspaces=3)],
        {"bob": 1},
        "bob",
    )
    assert places == 2


# --- Capacité machine contre quota de forfait ------------------------------
#
# La capacité prime sur tout : elle dit ce que la machine supporte sans
# planter. Un forfait plus généreux ne fabrique pas de la RAM.


def test_la_capacite_machine_plafonne_un_forfait_plus_genereux() -> None:
    ownership = _ownership(capacity_workspaces=3, offer_max_workspaces=10)
    assert limite_effective(ownership) == (3, "machine")


def test_un_forfait_plus_petit_borne_avant_la_capacite() -> None:
    # Rien de physique ici : on n'a payé que trois places sur une machine qui
    # en tient dix. La limite est commerciale, et le message doit le dire.
    ownership = _ownership(capacity_workspaces=10, offer_max_workspaces=3)
    assert limite_effective(ownership) == (3, "forfait")


def test_a_egalite_c_est_la_machine_qui_est_nommee() -> None:
    ownership = _ownership(capacity_workspaces=5, offer_max_workspaces=5)
    assert limite_effective(ownership) == (5, "machine")


def test_sans_forfait_la_capacite_machine_s_applique_seule() -> None:
    assert limite_effective(_ownership(capacity_workspaces=4)) == (4, "machine")


def test_sans_capacite_connue_le_forfait_s_applique_seul() -> None:
    ownership = _ownership(capacity_workspaces=None, offer_max_workspaces=4)
    assert limite_effective(ownership) == (4, "forfait")


def test_sans_aucun_plafond_rien_ne_borne() -> None:
    ownership = _ownership(capacity_workspaces=None, offer_max_workspaces=None)
    assert limite_effective(ownership) == (None, "")


def test_un_forfait_genereux_ne_fait_pas_planter_la_machine() -> None:
    with pytest.raises(QuotaDepasse, match="sans planter"):
        verifier_creation(
            _ownership(capacity_workspaces=3, offer_max_workspaces=10),
            [],
            {"alice": 3},
            "alice",
        )


def test_le_refus_commercial_ne_parle_pas_de_plantage() -> None:
    # L'un appelle une machine plus grosse, l'autre un forfait supérieur : les
    # confondre envoie l'utilisateur payer pour rien.
    with pytest.raises(QuotaDepasse, match="quota du forfait"):
        verifier_creation(
            _ownership(capacity_workspaces=10, offer_max_workspaces=3),
            [],
            {"alice": 3},
            "alice",
        )


def test_les_places_restantes_suivent_le_plafond_le_plus_bas() -> None:
    ownership = _ownership(capacity_workspaces=3, offer_max_workspaces=10)
    assert places_pour(ownership, [], {"alice": 1}, "alice") == 2
