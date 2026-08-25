"""Masque de numérotation `{count++}` dans le nom d'une machine.

Un profil fige les paramètres de création — le nom compris. Sans variable,
toutes les machines qui en sortent porteraient le même nom et la seconde
création échouerait. `{count++}` numérote donc la machine à sa création.

Pour une VM de test, le compteur est celui du workspace (`<N+1>`). Hors
workspace — un host généré depuis un profil — il n'y a pas de compteur : on le
déduit des noms déjà pris, en cherchant le premier indice libre pour ce gabarit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

COUNT_MASK_RE = re.compile(r"\{count\+\+\}")


def has_count_mask(valeur: str) -> bool:
    return COUNT_MASK_RE.search(valeur) is not None


def next_index(pattern: str, existing_names: Iterable[str]) -> int:
    """Premier indice libre pour ce gabarit, en partant de 1.

    On ne compte pas les machines : on lit les indices DÉJÀ PRIS par le gabarit.
    Compter donnerait le mauvais résultat dès qu'une machine du milieu a été
    supprimée — `host-1` et `host-3` font deux machines, et `host-2` est libre.
    """
    # Le gabarit devient une regex : tout est littéral sauf le masque, qui
    # capture un entier. `re.escape` traite les points et tirets du nom.
    morceaux = [re.escape(p) for p in COUNT_MASK_RE.split(pattern)]
    if len(morceaux) < 2:
        raise ValueError(f"pattern {pattern!r} ne contient pas de masque {{count++}}")
    motif = re.compile(r"^" + r"(\d+)".join(morceaux) + r"$")

    pris: set[int] = set()
    for nom in existing_names:
        m = motif.match(nom)
        if m:
            pris.update(int(g) for g in m.groups())

    indice = 1
    while indice in pris:
        indice += 1
    return indice


def resolve_count_mask(valeur: str, existing_names: Iterable[str]) -> str:
    """Remplace `{count++}` par le premier indice libre. Sans masque : inchangé."""
    if not has_count_mask(valeur):
        return valeur
    return COUNT_MASK_RE.sub(str(next_index(valeur, existing_names)), valeur)
