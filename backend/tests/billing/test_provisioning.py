"""Ce que la plateforme décide de provisionner quand quelqu'un souscrit.

Le module ne provisionne rien lui-même : il rend un verdict motivé, que
l'orchestrateur exécutera. C'est ce qui rend ces règles testables sans Proxmox,
sans base, et sans effet de bord — et c'est là que se joue le risque : une
décision fausse crée une VM en trop, ou n'en crée aucune à un client qui paie.
"""

from __future__ import annotations

import pytest

from portal.billing.provisioning import (
    NOEUD_DEDIE,
    HostDisponible,
    decider,
)


def _pool(*places: tuple[str, int]) -> list[HostDisponible]:
    return [HostDisponible(host_name=nom, places_restantes=n) for nom, n in places]


# ─── Seuls deux événements provisionnent ─────────────────────────────────────


@pytest.mark.parametrize("kind", ["renouvellement", "echec_paiement", "resiliation"])
def test_les_autres_evenements_ne_provisionnent_rien(kind: str) -> None:
    d = decider(evenement=kind, hosting_type="mutualise", deja_provisionne=False, pool=_pool())
    assert d.action == "rien"


@pytest.mark.parametrize("kind", ["debut_essai", "activation"])
def test_debut_essai_et_activation_provisionnent_pareil(kind: str) -> None:
    """`debut_essai` donne l'accès tout de suite, `activation` au premier
    paiement réel — le provisioning est le même, seul le moment change."""
    d = decider(evenement=kind, hosting_type="dedie", deja_provisionne=False, pool=_pool())
    assert d.action == "creer_vm_dediee"


# ─── Idempotence ─────────────────────────────────────────────────────────────


def test_activation_apres_essai_ne_reprovisionne_pas() -> None:
    """Le cas qui coûte cher : l'essai a déjà créé la machine, le premier
    paiement ne doit pas en créer une seconde."""
    d = decider(evenement="activation", hosting_type="dedie", deja_provisionne=True, pool=_pool())
    assert d.action == "rien"
    assert "déjà" in d.motif


# ─── Dédié ───────────────────────────────────────────────────────────────────


def test_dedie_cree_une_vm_sur_le_noeud_prevu() -> None:
    """pve2 porte la RTX 4090, réservée à l'inférence LLM : aucune VM d'abonné
    n'y est créée."""
    d = decider(evenement="debut_essai", hosting_type="dedie", deja_provisionne=False, pool=_pool())
    assert d.action == "creer_vm_dediee"
    assert d.noeud == NOEUD_DEDIE == "pve"


def test_dedie_ignore_le_pool_mutualise() -> None:
    """Un forfait dédié ne se sert pas dans le pool, même s'il y a de la place —
    c'est précisément ce pour quoi le client paie."""
    d = decider(
        evenement="debut_essai",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(("mut-01", 5)),
    )
    assert d.action == "creer_vm_dediee"


# ─── Mutualisé ───────────────────────────────────────────────────────────────


def test_mutualise_sans_pool_ouvre_un_host() -> None:
    d = decider(
        evenement="activation", hosting_type="mutualise", deja_provisionne=False, pool=_pool()
    )
    assert d.action == "creer_host_mutualise"


def test_mutualise_pool_plein_ouvre_un_host() -> None:
    """« Créer un nouveau host seulement si tous les existants sont pleins »."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-01", 0), ("mut-02", 0)),
    )
    assert d.action == "creer_host_mutualise"


def test_mutualise_remplit_avant_d_ouvrir() -> None:
    """Entre deux hosts qui conviennent, on prend celui qui a le MOINS de place :
    remplir une machine avant d'en ouvrir une autre est ce que demande la fiche,
    et ça garde les grandes libres pour ce qui ne tient nulle part ailleurs."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-01", 7), ("mut-02", 2), ("mut-03", 0)),
    )
    assert d.action == "assigner_host"
    assert d.host_name == "mut-02"


def test_choix_deterministe_a_egalite() -> None:
    """Deux hosts à égalité : l'ordre alphabétique tranche. Un tirage instable
    rendrait un rejeu d'événement non idempotent."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-b", 3), ("mut-a", 3)),
    )
    assert d.host_name == "mut-a"


def test_le_motif_nomme_la_machine_choisie() -> None:
    """Le verdict est journalisé : il doit se lire sans relire le code."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-01", 4)),
    )
    assert "mut-01" in d.motif


def test_places_restantes_negatives_traitees_comme_pleines() -> None:
    """Une machine sur-souscrite (capacité réduite après coup) ne doit pas
    devenir la cible d'une assignation supplémentaire."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-01", -2)),
    )
    assert d.action == "creer_host_mutualise"
