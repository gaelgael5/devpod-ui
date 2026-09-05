"""Répartition d'un quota d'abonnement sur une ou plusieurs machines.

Deux plafonds, et c'est leur SÉPARATION qui compte : le quota du forfait est
commercial, la capacité de la machine est physique. Les confondre produit un
message de refus qui envoie l'utilisateur payer là où il fallait une machine
plus grosse — ou l'inverse.
"""

from __future__ import annotations

import pytest

from portal.billing.allocation import (
    Part,
    QuotaDepasse,
    parts_disponibles,
    verifier_creation_pool,
    verifier_part,
)


def test_quota_illimite_ne_borne_rien():
    """`None` = le forfait ne compte pas les workspaces (cas des offres dédiées)."""
    assert parts_disponibles(None, [Part(host_name="a", allocated_workspaces=50)]) is None


def test_reste_du_quota_apres_les_parts_deja_posees():
    parts = [
        Part(host_name="a", allocated_workspaces=3),
        Part(host_name="b", allocated_workspaces=2),
    ]
    assert parts_disponibles(10, parts) == 5


def test_quota_epuise_rend_zero_jamais_un_negatif():
    """Un quota dépassé — abaissement d'offre, reprise manuelle — rend 0.

    Rendre un négatif ferait passer un `> 0` ailleurs pour une réserve.
    """
    assert parts_disponibles(2, [Part(host_name="a", allocated_workspaces=5)]) == 0


def test_une_part_dans_le_quota_et_la_capacite_passe():
    verifier_part(quota_forfait=10, parts=[], host_name="vm1", demande=3, capacite_restante=8)


def test_depassement_du_quota_nomme_le_forfait():
    with pytest.raises(QuotaDepasse) as err:
        verifier_part(
            quota_forfait=5,
            parts=[Part(host_name="vm1", allocated_workspaces=4)],
            host_name="vm2",
            demande=3,
            capacite_restante=100,
        )
    assert "forfait" in str(err.value)


def test_depassement_de_la_capacite_nomme_la_machine():
    """La machine passe avant : on n'achète pas de la RAM avec un abonnement."""
    with pytest.raises(QuotaDepasse) as err:
        verifier_part(quota_forfait=100, parts=[], host_name="vm1", demande=6, capacite_restante=4)
    assert "vm1" in str(err.value)
    assert "forfait" not in str(err.value)


def test_capacite_inconnue_refuse_plutot_que_de_supposer():
    """`None` = capacité non renseignée. Poser dessus, c'est parier sur la RAM."""
    with pytest.raises(QuotaDepasse):
        verifier_part(
            quota_forfait=10, parts=[], host_name="brut", demande=1, capacite_restante=None
        )


def test_reposer_sur_la_meme_machine_remplace_la_part():
    """Rejouer un webhook ne doit pas cumuler deux parts sur la même machine.

    La part existante sur `vm1` vaut 4 ; la porter à 6 consomme 6 du quota, pas
    10. Sans cette règle, un rejeu épuiserait le quota d'un abonné qui n'a rien
    demandé de plus.
    """
    verifier_part(
        quota_forfait=6,
        parts=[Part(host_name="vm1", allocated_workspaces=4)],
        host_name="vm1",
        demande=6,
        capacite_restante=10,
    )


def test_part_nulle_ou_negative_refusee():
    with pytest.raises(ValueError):
        Part(host_name="vm1", allocated_workspaces=0)


# ─── Création d'un workspace sur une machine du pool ─────────────────────────


def test_pool_sous_la_part_la_creation_passe():
    verifier_creation_pool(
        host_name="mut-01", part_allouee=3, mes_workspaces=2, capacite=10, utilises=5
    )


def test_pool_sans_part_le_refus_nomme_l_abonnement_manquant():
    """Sans abonnement donnant une place ici, on ne crée rien — et le message
    dit quoi faire, pas juste « non »."""
    with pytest.raises(QuotaDepasse) as err:
        verifier_creation_pool(
            host_name="mut-01", part_allouee=0, mes_workspaces=0, capacite=10, utilises=0
        )
    assert "abonnement" in str(err.value)
    assert "mut-01" in str(err.value)


def test_pool_part_epuisee_le_refus_nomme_le_quota_du_forfait():
    with pytest.raises(QuotaDepasse) as err:
        verifier_creation_pool(
            host_name="mut-01", part_allouee=2, mes_workspaces=2, capacite=10, utilises=4
        )
    assert "forfait" in str(err.value)
    assert "2/2" in str(err.value)


def test_pool_machine_pleine_prime_sur_la_part_restante():
    """La capacité physique gouverne : même avec une part disponible, une
    machine pleine ne prend plus rien — et le message appelle une machine,
    pas un forfait."""
    with pytest.raises(QuotaDepasse) as err:
        verifier_creation_pool(
            host_name="mut-01", part_allouee=5, mes_workspaces=1, capacite=4, utilises=4
        )
    assert "capacité" in str(err.value)
    assert "forfait" not in str(err.value)


def test_pool_capacite_inconnue_ne_bloque_pas_une_part_valide():
    """`None` = non renseignée. La part a été accordée au provisionnement, où la
    capacité était connue : la retirer après coup bloquerait un droit acquis."""
    verifier_creation_pool(
        host_name="mut-01", part_allouee=2, mes_workspaces=1, capacite=None, utilises=9
    )
