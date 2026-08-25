"""Selection des deploiements orphelins (noeud disparu de l'inventaire)."""

from __future__ import annotations

from portal.compose.models import ComposeDeployment
from portal.compose.orphans import select_orphans


def _dep(name: str, node_id: str) -> ComposeDeployment:
    return ComposeDeployment(
        uid=f"uid-{name}-{node_id}",
        id=name,
        template_id="alloy-collector",
        template_version="1",
        node_id=node_id,
        owner_login="alice",
        status="running",
    )


def test_retient_les_deploiements_dont_le_noeud_a_disparu() -> None:
    deps = [_dep("chromium", "host-test-105-2"), _dep("alloy", "host-test-106-1")]

    orphelins = select_orphans(deps, ["host-test-106-1"])

    assert [d.node_id for d in orphelins] == ["host-test-105-2"]


def test_ne_retient_rien_quand_tous_les_noeuds_existent() -> None:
    deps = [_dep("a", "n1"), _dep("b", "n2")]

    assert select_orphans(deps, ["n1", "n2"]) == []


def test_un_inventaire_vide_rend_tout_orphelin() -> None:
    """Le cas est reel — un portail sans host — et il doit rester explicite :
    c'est bien la liste des lignes a purger, pas un garde-fou implicite."""
    deps = [_dep("a", "n1")]

    assert len(select_orphans(deps, [])) == 1


def test_un_host_non_eligible_au_deploiement_n_est_pas_orphelin() -> None:
    """L'inventaire passe en entree doit etre COMPLET. Un host d'usage
    « autres » est exclu des cibles de deploiement mais existe bel et bien :
    le purger emporterait des services qui tournent."""
    deps = [_dep("a", "host-inventaire")]

    assert select_orphans(deps, ["host-inventaire"]) == []


def test_plusieurs_lignes_du_meme_noeud_sortent_toutes() -> None:
    deps = [
        _dep("alloy-devpod", "host-test-106-1"),
        _dep("chromium", "host-test-106-1"),
        _dep("alloy", "host-vivant"),
    ]

    orphelins = select_orphans(deps, ["host-vivant"])

    assert sorted(d.id for d in orphelins) == ["alloy-devpod", "chromium"]
