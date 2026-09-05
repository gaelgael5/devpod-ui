"""Ce que la plateforme décide de provisionner quand quelqu'un souscrit.

Le module ne provisionne rien lui-même : il rend un verdict motivé, que
l'orchestrateur exécutera. C'est ce qui rend ces règles testables sans Proxmox,
sans base, et sans effet de bord — et c'est là que se joue le risque : une
décision fausse crée une VM en trop, ou n'en crée aucune à un client qui paie.
"""

from __future__ import annotations

import pytest

from portal.billing.cible import Cible
from portal.billing.provisioning import (
    HostDisponible,
    decider,
)


def _pool(*places: tuple[str, int]) -> list[HostDisponible]:
    return [HostDisponible(host_name=nom, places_restantes=n) for nom, n in places]


def _cible(noeud: str = "pve") -> Cible:
    return Cible(
        host_profile="host-standard",
        machine_profile="pve-4g",
        hypervisor="pve-a",
        noeud=noeud,
    )

# ─── Seuls deux événements provisionnent ─────────────────────────────────────


@pytest.mark.parametrize("kind", ["renouvellement", "echec_paiement", "resiliation"])
def test_les_autres_evenements_ne_provisionnent_rien(kind: str) -> None:
    d = decider(evenement=kind, hosting_type="mutualise", deja_provisionne=False, pool=_pool())
    assert d.action == "rien"


@pytest.mark.parametrize("kind", ["debut_essai", "activation"])
def test_debut_essai_et_activation_provisionnent_pareil(kind: str) -> None:
    """`debut_essai` donne l'accès tout de suite, `activation` au premier
    paiement réel — le provisioning est le même, seul le moment change."""
    d = decider(
        evenement=kind,
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(),
        cible=_cible(),
    )
    assert d.action == "creer_vm_dediee"


# ─── Idempotence ─────────────────────────────────────────────────────────────


def test_activation_apres_essai_ne_reprovisionne_pas() -> None:
    """Le cas qui coûte cher : l'essai a déjà créé la machine, le premier
    paiement ne doit pas en créer une seconde."""
    d = decider(evenement="activation", hosting_type="dedie", deja_provisionne=True, pool=_pool())
    assert d.action == "rien"
    assert "déjà" in d.motif


# ─── Dédié ───────────────────────────────────────────────────────────────────


def test_dedie_cree_une_vm_sur_le_noeud_de_sa_cible() -> None:
    d = decider(
        evenement="debut_essai",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(),
        cible=_cible(),
    )
    assert d.action == "creer_vm_dediee"
    assert d.noeud == "pve"


def test_dedie_ignore_le_pool_mutualise() -> None:
    """Un forfait dédié ne se sert pas dans le pool, même s'il y a de la place —
    c'est précisément ce pour quoi le client paie."""
    d = decider(
        evenement="debut_essai",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(("mut-01", 5)),
        cible=_cible(),
    )
    assert d.action == "creer_vm_dediee"


# ─── Mutualisé ───────────────────────────────────────────────────────────────


def test_mutualise_sans_pool_ouvre_un_host() -> None:
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(),
        cible=_cible(),
    )
    assert d.action == "creer_host_mutualise"


def test_mutualise_pool_plein_ouvre_un_host() -> None:
    """« Créer un nouveau host seulement si tous les existants sont pleins »."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("mut-01", 0), ("mut-02", 0)),
        cible=_cible(),
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
        cible=_cible(),
    )
    assert d.action == "creer_host_mutualise"


# ─── Capacité non déclarée ───────────────────────────────────────────────────


def test_host_sans_capacite_declaree_reste_utilisable_mais_en_dernier() -> None:
    """`capacity_workspaces` absent du profil de host : on ne sait pas ce que la
    machine tient. On ne bloque pas un client qui paie pour autant — on la garde
    en dernier recours, derrière toute machine dont la capacité est connue."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=[
            HostDisponible(host_name="mut-inconnu", places_restantes=None),
            HostDisponible(host_name="mut-01", places_restantes=6),
        ],
    )
    assert d.action == "assigner_host"
    assert d.host_name == "mut-01"


def test_host_sans_capacite_declaree_choisi_faute_de_mieux() -> None:
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=[
            HostDisponible(host_name="mut-inconnu", places_restantes=None),
            HostDisponible(host_name="mut-plein", places_restantes=0),
        ],
    )
    assert d.action == "assigner_host"
    assert d.host_name == "mut-inconnu"
    # Le motif doit signaler le trou de configuration, pas le masquer.
    assert "non déclarée" in d.motif


# ─── Sur quel gabarit : la cible résolue depuis les profils de l'offre ────────


def test_la_vm_dediee_nait_sur_le_noeud_de_l_hyperviseur_resolu() -> None:
    """Le nœud ne se devine plus : il vient de l'hyperviseur que la chaîne de
    profils a désigné."""
    d = decider(
        evenement="activation",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(),
        cible=_cible(noeud="pve3"),
    )

    assert d.action == "creer_vm_dediee"
    assert d.noeud == "pve3"
    assert d.cible is not None
    assert d.cible.machine_profile == "pve-4g"


def test_le_host_mutualise_ouvert_porte_aussi_sa_cible() -> None:
    """Ouvrir une machine mutualisée, c'est ouvrir une machine : sans gabarit,
    l'exécuteur ne saurait pas plus quoi monter que pour une dédiée."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(),
        cible=_cible(),
    )

    assert d.action == "creer_host_mutualise"
    assert d.cible is not None


def test_assigner_une_place_existante_ne_demande_aucune_cible() -> None:
    """On ne monte rien : le gabarit de la machine d'accueil a été choisi le
    jour où elle a été montée."""
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("host-a", 2)),
        cible=None,
    )

    assert d.action == "assigner_host"
    assert d.host_name == "host-a"


def test_sans_cible_resolue_le_verdict_est_un_refus_motive() -> None:
    """Surtout pas « rien à faire » : le client a payé. L'écart doit être
    traçable et rejouable, pas silencieux."""
    d = decider(
        evenement="activation",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(),
        cible=None,
    )

    assert d.action == "impossible"
    assert "profil" in d.motif
    assert d.noeud is None


def test_sans_cible_l_ouverture_d_un_host_mutualise_est_refusee_aussi() -> None:
    d = decider(
        evenement="activation",
        hosting_type="mutualise",
        deja_provisionne=False,
        pool=_pool(("plein", 0)),
        cible=None,
    )

    assert d.action == "impossible"


def test_un_evenement_non_provisionnant_ne_reclame_pas_de_cible() -> None:
    """L'absence de gabarit n'est un problème que si l'on doit monter quelque
    chose."""
    d = decider(
        evenement="renouvellement",
        hosting_type="dedie",
        deja_provisionne=False,
        pool=_pool(),
        cible=None,
    )

    assert d.action == "rien"
