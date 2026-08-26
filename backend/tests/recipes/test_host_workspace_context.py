"""Contexte du workspace injecte dans les recettes de host (ticket 29f3c418).

Une recette de host ne recevait que ses propres options : elle n'avait aucun
moyen de connaitre le workspace auquel la machine est rattachee. Or le depot a
cloner appartient au WORKSPACE, pas a la recette — le coder en dur la rend fausse
partout ailleurs, et le saisir a la main redemande a chaque fois une valeur que
le portail connait deja.

Meme motif que `PORTAL_INJECTED_VARS` cote compose : passage par
l'ENVIRONNEMENT, valeurs quotees, jamais de substitution textuelle.
"""

from __future__ import annotations

import pytest

from portal.recipes.host_apply import (
    CONTEXT_VARS,
    HostApplyError,
    build_apply_script,
    build_context_exports,
)
from portal.recipes.models import RecipeMeta


def _exporte(script: str, nom: str, valeur: str) -> bool:
    """`shlex.quote` ne quote QUE si c'est necessaire : `main` sort nu, une URL
    aussi. Comparer a la forme quotee ferait echouer le test sur des valeurs
    parfaitement sures."""
    import shlex

    return f"export {nom}={shlex.quote(valeur)}\n" in script

_CONTEXTE = {
    "WORKSPACE_ID": "admin-termix-mobile",
    "WORKSPACE_GIT_URL": "https://github.com/ag-flow/termix-mobile.git",
    "WORKSPACE_GIT_REF": "main",
}


def _meta() -> RecipeMeta:
    return RecipeMeta(
        id="android-emulator",
        version="1.0.0",
        scope="host",
        host_usages=["tests"],
    )


# ─── AC1 — contexte injecte ──────────────────────────────────────────────────


def test_les_trois_variables_sont_exportees() -> None:
    script = build_apply_script(_meta(), "#!/bin/sh\ntrue\n", {}, _CONTEXTE)

    for nom, valeur in _CONTEXTE.items():
        assert _exporte(script, nom, valeur), nom


def test_le_contexte_precede_le_script() -> None:
    """Exporte APRES le script, la variable n'aurait servi a rien."""
    script = build_apply_script(_meta(), "#!/bin/sh\ntrue\n", {}, _CONTEXTE)

    assert script.index("export WORKSPACE_GIT_URL") < script.index('sh "$D/install.sh"')


def test_contexte_et_options_cohabitent() -> None:
    script = build_apply_script(_meta(), "x", {"avd_ram": "4096"}, _CONTEXTE)

    assert _exporte(script, "RECIPE_OPT_AVD_RAM", "4096")
    assert _exporte(script, "WORKSPACE_GIT_REF", "main")


# ─── AC4 — absence de contexte, sans erreur ──────────────────────────────────


@pytest.mark.parametrize("vide", [None, {}])
def test_sans_contexte_rien_n_est_exporte(vide: dict[str, str] | None) -> None:
    """Un host de workspaces ou un serveur de ressources n'a pas de depot a
    faire connaitre : ce n'est pas une erreur."""
    assert build_context_exports(vide) == ""


def test_sans_contexte_le_script_reste_celui_d_avant() -> None:
    """AC6 — non-regression : le script produit doit etre identique a celui
    d'avant le changement pour une recette qui ignore le contexte."""
    avec = build_apply_script(_meta(), "x", {"a": "1"}, None)
    sans_argument = build_apply_script(_meta(), "x", {"a": "1"})

    assert avec == sans_argument
    assert "WORKSPACE_" not in avec


def test_une_valeur_vide_n_est_pas_exportee() -> None:
    """Le script consommateur enchaine des replis `${WORKSPACE_GIT_URL:-}` :
    une variable definie mais VIDE se distingue mal d'une absence."""
    exports = build_context_exports({**_CONTEXTE, "WORKSPACE_GIT_REF": ""})

    assert "WORKSPACE_GIT_REF" not in exports
    assert "WORKSPACE_GIT_URL" in exports


# ─── AC5 — injection sure ────────────────────────────────────────────────────


def test_une_valeur_hostile_est_quotee() -> None:
    hostile = "https://x/a.git; rm -rf / #"
    exports = build_context_exports({"WORKSPACE_GIT_URL": hostile})

    assert exports == "export WORKSPACE_GIT_URL='https://x/a.git; rm -rf / #'\n"
    # Le `;` ne doit jamais se retrouver hors des quotes : il y serait un
    # separateur de commandes.
    assert not exports.replace("'https://x/a.git; rm -rf / #'", "").count(";")


def test_une_valeur_avec_guillemets_est_quotee() -> None:
    exports = build_context_exports({"WORKSPACE_ID": "a'b\"c d"})

    assert exports.startswith("export WORKSPACE_ID=")
    assert "\n" not in exports[: -1]


def test_une_variable_hors_liste_est_refusee() -> None:
    """Les noms viennent du code du portail. Un jeu de cles venu d'ailleurs
    pourrait sinon definir PATH ou LD_PRELOAD pour le script."""
    with pytest.raises(HostApplyError) as exc:
        build_context_exports({"PATH": "/tmp/evil"})

    assert "PATH" in str(exc.value)


def test_la_liste_autorisee_est_celle_du_ticket() -> None:
    assert set(CONTEXT_VARS) == {"WORKSPACE_ID", "WORKSPACE_GIT_URL", "WORKSPACE_GIT_REF"}


# ─── AC3 — l'option explicite reste prioritaire ──────────────────────────────


def test_l_option_et_le_contexte_sont_deux_variables_distinctes() -> None:
    """La priorite se joue DANS le script de la recette
    (`${RECIPE_OPT_REPO_URL:-${WORKSPACE_GIT_URL:-}}`) : le portail doit donc
    exporter les deux sans que l'une ecrase l'autre."""
    script = build_apply_script(
        _meta(), "x", {"repo_url": "https://saisi/a.git"}, _CONTEXTE
    )

    assert _exporte(script, "RECIPE_OPT_REPO_URL", "https://saisi/a.git")
    assert _exporte(script, "WORKSPACE_GIT_URL", _CONTEXTE["WORKSPACE_GIT_URL"])
