"""Portée d'une recette : workspace (défaut) ou host.

Une recette de host s'installe SUR LA MACHINE, avec les droits d'administration
— pas dans un conteneur qui borne les dégâts. La déclaration de portée et des
familles visées est donc la première barrière : le portail refuse une
application sur une famille non déclarée.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.recipes.models import RecipeMeta


def _meta(**extra: object) -> dict[str, object]:
    return {"id": "android-emulator", **extra}


def test_portee_workspace_par_defaut() -> None:
    """Le catalogue existant ne porte aucun `scope` : il doit rester intact,
    sans migration ni régression au provisionnement."""
    meta = RecipeMeta.model_validate(_meta())

    assert meta.scope == "workspace"
    assert meta.host_usages == []


def test_portee_host_declare_ses_familles() -> None:
    meta = RecipeMeta.model_validate(_meta(scope="host", host_usages=["workspaces", "tests"]))

    assert meta.scope == "host"
    assert meta.host_usages == ["workspaces", "tests"]


def test_portee_host_exige_au_moins_une_famille() -> None:
    """Sans famille déclarée, la recette serait applicable partout ou nulle part :
    les deux sont de mauvaises réponses pour de l'exécution privilégiée."""
    with pytest.raises(ValidationError, match="host_usages"):
        RecipeMeta.model_validate(_meta(scope="host"))


def test_famille_inconnue_refusee() -> None:
    with pytest.raises(ValidationError):
        RecipeMeta.model_validate(_meta(scope="host", host_usages=["nimportequoi"]))


def test_familles_interdites_sur_une_recette_de_workspace() -> None:
    """Déclarer des familles sans passer en `scope: host` trahit une méta
    incohérente — on la refuse plutôt que d'ignorer le champ en silence."""
    with pytest.raises(ValidationError, match="scope"):
        RecipeMeta.model_validate(_meta(host_usages=["workspaces"]))


def test_familles_dedupliquees_et_ordonnees() -> None:
    meta = RecipeMeta.model_validate(
        _meta(scope="host", host_usages=["tests", "workspaces", "tests"])
    )

    assert meta.host_usages == ["tests", "workspaces"]


def test_portee_inconnue_refusee() -> None:
    with pytest.raises(ValidationError):
        RecipeMeta.model_validate(_meta(scope="cluster"))


class TestCompatibilite:
    """`applies_to` répond à « cette recette peut-elle viser CETTE machine ? »."""

    def test_recette_de_host_sur_une_famille_declaree(self) -> None:
        meta = RecipeMeta.model_validate(_meta(scope="host", host_usages=["workspaces"]))

        assert meta.applies_to_host("workspaces") is True

    def test_recette_de_host_sur_une_famille_non_declaree(self) -> None:
        meta = RecipeMeta.model_validate(_meta(scope="host", host_usages=["workspaces"]))

        assert meta.applies_to_host("tests") is False

    def test_une_recette_de_workspace_ne_vise_aucun_host(self) -> None:
        # Le garde-fou principal : rien du catalogue existant ne devient
        # applicable sur une machine par accident.
        meta = RecipeMeta.model_validate(_meta())

        for usage in ("workspaces", "tests", "portail", "ressources", "autres"):
            assert meta.applies_to_host(usage) is False
