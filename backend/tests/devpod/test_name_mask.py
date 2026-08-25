"""Masque `{count++}` resolu hors workspace (host genere depuis un profil)."""

from __future__ import annotations

import pytest

from portal.devpod.name_mask import has_count_mask, next_index, resolve_count_mask


def test_detecte_le_masque() -> None:
    assert has_count_mask("host-dev-{count++}")
    assert not has_count_mask("host-dev-01")
    # `{count}` seul n'est PAS le masque : il a la forme d'un placeholder de
    # script (`{NOM}`) et creerait une ambiguite.
    assert not has_count_mask("host-dev-{count}")


def test_premier_indice_quand_rien_n_existe() -> None:
    assert next_index("host-dev-{count++}", []) == 1


def test_saute_les_indices_pris() -> None:
    assert next_index("host-dev-{count++}", ["host-dev-1", "host-dev-2"]) == 3


def test_reprend_un_trou_laisse_par_une_suppression() -> None:
    """Compter les machines donnerait 3 alors que `host-dev-2` est libre — et
    le nom compte : c'est lui qui doit rester unique, pas leur nombre."""
    assert next_index("host-dev-{count++}", ["host-dev-1", "host-dev-3"]) == 2


def test_ignore_les_noms_d_un_autre_gabarit() -> None:
    noms = ["host-test-1", "autre-9", "host-dev-1"]
    assert next_index("host-dev-{count++}", noms) == 2


def test_les_caracteres_speciaux_du_gabarit_restent_litteraux() -> None:
    """Sans echappement, le `.` de `host.dev` matcherait n'importe quel
    caractere et `hostXdev-1` passerait pour un indice pris."""
    assert next_index("host.dev-{count++}", ["hostXdev-1"]) == 1


def test_resolution_complete() -> None:
    assert resolve_count_mask("host-dev-{count++}", ["host-dev-1"]) == "host-dev-2"


def test_valeur_sans_masque_inchangee() -> None:
    assert resolve_count_mask("host-dev-01", ["host-dev-01"]) == "host-dev-01"


def test_next_index_refuse_un_gabarit_sans_masque() -> None:
    with pytest.raises(ValueError):
        next_index("host-dev-01", [])
