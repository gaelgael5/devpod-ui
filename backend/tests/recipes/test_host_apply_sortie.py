"""Nettoyage des sorties remontees a l'utilisateur.

Le script d'installation colore ses messages. Remontes tels quels, les codes
ANSI s'affichaient en clair dans l'interface :
`RuntimeError: ... : \x1b[1;31mERROR: pas d'acces a /dev/kvm\x1b[0m`
"""

from __future__ import annotations

from portal.recipes.host_apply import nettoyer_sortie


def test_retire_les_codes_couleur() -> None:
    brut = "\x1b[1;31mERROR: pas d'acces a /dev/kvm\x1b[0m"

    assert nettoyer_sortie(brut) == "ERROR: pas d'acces a /dev/kvm"


def test_conserve_un_message_deja_propre() -> None:
    assert nettoyer_sortie("echec simple") == "echec simple"


def test_condense_les_lignes_vides() -> None:
    # Un preflight verbeux laisse des blocs vides qui noient le message utile.
    assert nettoyer_sortie("a\n\n\n\nb") == "a\nb"


def test_garde_la_derniere_ligne_utile() -> None:
    # C'est elle qui porte la cause ; on ne la tronque pas.
    brut = "\x1b[33m==> Preflight\x1b[0m\n  /dev/kvm existe\n\x1b[1;31mERROR: pas d'acces\x1b[0m"

    assert nettoyer_sortie(brut).endswith("ERROR: pas d'acces")


def test_sortie_vide() -> None:
    assert nettoyer_sortie("") == ""


def test_borne_une_sortie_enorme() -> None:
    # Un `sdkmanager` bavard peut cracher des milliers de lignes : les remonter
    # toutes dans une bulle d'erreur ne sert personne.
    nettoye = nettoyer_sortie("x" * 5000)

    assert len(nettoye) <= 2000
    # C'est le DEBUT qu'on coupe : la cause est toujours en fin de sortie.
    assert nettoye.startswith("…")
