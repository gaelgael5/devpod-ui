"""Paramètres d'une recette de host.

Ils traversent un shell distant privilégié : validés contre leur déclaration,
et injectés en variables d'environnement quotées — jamais par substitution
textuelle dans une commande.
"""

from __future__ import annotations

import pytest

from portal.recipes.host_apply import HostApplyError, build_apply_script, resolve_options
from portal.recipes.models import RecipeMeta


def _meta(**options: object) -> RecipeMeta:
    return RecipeMeta.model_validate(
        {
            "id": "android-emulator",
            "scope": "host",
            "host_usages": ["tests"],
            "options": options or {"api": {"default": "35"}},
        }
    )


class TestResolution:
    def test_applique_les_defauts_declares(self) -> None:
        assert resolve_options(_meta(), {}) == {"api": "35"}

    def test_une_valeur_fournie_remplace_le_defaut(self) -> None:
        assert resolve_options(_meta(), {"api": "34"}) == {"api": "34"}

    def test_refuse_une_option_non_declaree(self) -> None:
        # Sans ça, n'importe quel nom arriverait dans l'environnement du script.
        with pytest.raises(HostApplyError, match="inconnue"):
            resolve_options(_meta(), {"cmd": "rm -rf /"})

    def test_refuse_une_valeur_avec_saut_de_ligne(self) -> None:
        # Un saut de ligne couperait l'affectation et ferait passer la suite
        # pour une commande.
        with pytest.raises(HostApplyError, match="valeur"):
            resolve_options(_meta(), {"api": "35\nrm -rf /"})

    def test_accepte_une_valeur_ordinaire(self) -> None:
        meta = _meta(avd={"default": "termix-test"})
        assert resolve_options(meta, {"avd": "mon-avd_2"})["avd"] == "mon-avd_2"


class TestInjection:
    def test_expose_l_option_en_variable_prefixee(self) -> None:
        script = build_apply_script(_meta(), "echo ok", {"api": "35"})

        assert "RECIPE_OPT_API=" in script

    def test_quote_la_valeur(self) -> None:
        # Une valeur avec espace ou métacaractère ne doit pas se scinder.
        script = build_apply_script(_meta(avd={"default": "x"}), "echo ok", {"avd": "mon avd"})

        assert "'mon avd'" in script

    def test_exporte_avant_d_executer(self) -> None:
        script = build_apply_script(_meta(), "echo ok", {"api": "35"})

        # Le lancement est direct (shebang honoré, bug c3864308) : l'export
        # doit précéder la ligne d'exécution, plus un `sh` explicite.
        assert script.index("RECIPE_OPT_API=") < script.index('\n"$D/install.sh"\n')

    def test_sans_option_le_script_reste_simple(self) -> None:
        script = build_apply_script(_meta(), "echo ok", {})

        assert "RECIPE_OPT_" not in script
