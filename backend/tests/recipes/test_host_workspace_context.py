"""Contexte du workspace, DECLARE par la recette (ticket 29f3c418).

Une recette de host ne recevait que ses propres options : elle n'avait aucun
moyen de connaitre le workspace auquel la machine est rattachee. Or le depot a
cloner appartient au WORKSPACE, pas a la recette.

Le contrat est DECLARATIF : la recette ecrit `from: workspace.git_url` sur
l'option concernee, dans son propre manifeste. Rien n'arrive dans
l'environnement du script qu'elle n'ait demande, et l'auteur lit dans le
fichier qu'il ecrit ce qui sera injecte — pas dans une convention a connaitre
par ailleurs.

Priorite arbitree par le portail, une fois : SAISIE > CONTEXTE > DEFAUT.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.recipes.host_apply import HostApplyError, build_apply_script, resolve_options
from portal.recipes.models import CONTEXT_KEYS, RecipeMeta, RecipeOption

_CONTEXTE = {
    "workspace.id": "admin-termix-mobile",
    "workspace.git_url": "https://github.com/ag-flow/termix-mobile.git",
    "workspace.git_ref": "main",
}


def _meta(**options: RecipeOption) -> RecipeMeta:
    return RecipeMeta(
        id="android-emulator",
        version="1.0.0",
        scope="host",
        host_usages=["tests"],
        options=options,
    )


def _liee() -> RecipeMeta:
    return _meta(
        repo_url=RecipeOption.model_validate({"from": "workspace.git_url"}),
        repo_ref=RecipeOption.model_validate({"from": "workspace.git_ref", "default": "main"}),
    )


# ─── La declaration vient de la source ───────────────────────────────────────


def test_le_vocabulaire_est_ferme() -> None:
    """Une cle inconnue est refusee A L'IMPORT du manifeste, pas ignoree en
    silence au moment de l'execution."""
    with pytest.raises(ValidationError) as exc:
        RecipeOption.model_validate({"from": "workspace.nope"})

    assert "workspace.git_url" in str(exc.value)


def test_les_cles_publiees_sont_celles_documentees() -> None:
    assert set(CONTEXT_KEYS) == {"workspace.id", "workspace.git_url", "workspace.git_ref"}


def test_une_option_sans_from_ignore_le_contexte() -> None:
    """Non declaree, non injectee : une recette existante ne change pas de
    comportement du seul fait que le portail connait le workspace."""
    meta = _meta(avd_ram=RecipeOption(default="4096"))

    assert resolve_options(meta, {}, _CONTEXTE) == {"avd_ram": "4096"}


# ─── Priorite SAISIE > CONTEXTE > DEFAUT ─────────────────────────────────────


def test_le_contexte_alimente_l_option_declaree() -> None:
    resolues = resolve_options(_liee(), {}, _CONTEXTE)

    assert resolues["repo_url"] == "https://github.com/ag-flow/termix-mobile.git"
    assert resolues["repo_ref"] == "main"


def test_la_saisie_l_emporte_sur_le_contexte() -> None:
    resolues = resolve_options(_liee(), {"repo_url": "https://autre/depot.git"}, _CONTEXTE)

    assert resolues["repo_url"] == "https://autre/depot.git"


def test_le_defaut_prend_le_relais_sans_contexte() -> None:
    """Machine sans workspace rattache : ni saisie ni contexte, le defaut du
    manifeste s'applique — et l'application se deroule normalement."""
    resolues = resolve_options(_liee(), {}, None)

    assert resolues["repo_url"] == ""
    assert resolues["repo_ref"] == "main"


def test_une_valeur_de_contexte_vide_ne_masque_pas_le_defaut() -> None:
    """Un workspace sans depot declare n'apporte rien : retomber sur le defaut
    vaut mieux qu'imposer une chaine vide."""
    resolues = resolve_options(_liee(), {}, {**_CONTEXTE, "workspace.git_ref": ""})

    assert resolues["repo_ref"] == "main"


def test_une_saisie_vide_ne_masque_pas_le_contexte() -> None:
    """Le formulaire envoie une chaine vide pour un champ non rempli : la
    traiter comme un choix priverait l'option de son heritage."""
    resolues = resolve_options(_liee(), {"repo_url": "   "}, _CONTEXTE)

    assert resolues["repo_url"] == "https://github.com/ag-flow/termix-mobile.git"


# ─── Ce qui arrive au script ─────────────────────────────────────────────────


def test_le_script_ne_recoit_que_des_RECIPE_OPT() -> None:
    """Un seul prefixe a connaitre. Aucune variable `WORKSPACE_*` implicite :
    le nom vient de l'option declaree dans le manifeste."""
    resolues = resolve_options(_liee(), {}, _CONTEXTE)
    script = build_apply_script(_liee(), "#!/bin/sh\ntrue\n", resolues)

    assert "export RECIPE_OPT_REPO_URL=" in script
    assert "WORKSPACE_" not in script


def test_la_valeur_heritee_est_quotee() -> None:
    """Passage par l'ENVIRONNEMENT et valeur quotee : jamais de substitution
    textuelle, ou une valeur bien choisie deviendrait du code."""
    meta = _meta(repo_url=RecipeOption.model_validate({"from": "workspace.git_url"}))
    hostile = "https://x/a.git a@b:c"
    resolues = resolve_options(meta, {}, {"workspace.git_url": hostile})

    script = build_apply_script(meta, "x", resolues)
    assert "export RECIPE_OPT_REPO_URL='https://x/a.git a@b:c'" in script


def test_une_valeur_heritee_invalide_est_refusee() -> None:
    """La validation porte sur la valeur FINALE : une URL heritee ne contourne
    pas le controle applique a une saisie."""
    meta = _meta(repo_url=RecipeOption.model_validate({"from": "workspace.git_url"}))

    with pytest.raises(HostApplyError):
        resolve_options(meta, {}, {"workspace.git_url": "https://x/a.git; rm -rf /"})
