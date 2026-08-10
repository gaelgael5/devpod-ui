"""Évaluation d'un filtre d'automate : JSONPath sur la réponse + opérateur booléen.

Le filtre interroge une API (ex. `GET /users/list`), extrait un ensemble de valeurs
par JSONPath (ex. `$.users[?(@.username=="{subject.login}")]`, variables rendues au
préalable), puis applique un opérateur : `exists` (au moins un match), `equals` /
`not_equals` (une valeur attendue est / n'est pas dans les matches). Comparaison de
scalaires insensible à la casse ; les booléens JSON deviennent `true`/`false`.
"""

from __future__ import annotations

from typing import Any

from jsonpath_ng.ext import parse as _parse  # type: ignore[import-untyped]

# Opérateurs supportés par l'IHM et le runner.
OPERATORS = ("exists", "not_exists", "equals", "not_equals")


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def evaluate(
    response: Any, jsonpath: str, operator: str, expected: str | None
) -> tuple[bool, list[Any]]:
    """Retourne `(passe, valeurs matchées)`. Lève ValueError si JSONPath/opérateur invalide."""
    try:
        expr = _parse(jsonpath)
    except Exception as exc:  # syntaxe JSONPath
        raise ValueError(f"JSONPath invalide : {exc}") from exc
    values = [m.value for m in expr.find(response)]
    if operator == "exists":
        return (len(values) > 0, values)
    if operator == "not_exists":
        return (len(values) == 0, values)
    exp = (expected or "").casefold()
    svals = [_scalar(v).casefold() for v in values]
    if operator == "equals":
        return (exp in svals, values)
    if operator == "not_equals":
        return (exp not in svals, values)
    raise ValueError(f"opérateur inconnu : {operator!r}")
