"""Masque `{count++}` dans les valeurs de parametres.

Sert au nom d'une machine : fige sans masque, toutes les machines d'un meme
profil porteraient le meme nom et la seconde creation echouerait sur un conflit.
"""

from __future__ import annotations

from portal.devpod.test_vm import substitute_param_vars


def _sub(valeur: str, n: int = 3) -> str:
    return substitute_param_vars({"NODE_NAME": valeur}, {"N": str(n), "N+1": str(n + 1)})[
        "NODE_NAME"
    ]


class TestMasqueCount:
    def test_remplace_par_le_prochain_numero(self) -> None:
        # Trois machines existantes : la prochaine porte le numero 4.
        assert _sub("host-test-{count++}") == "host-test-4"

    def test_premiere_machine(self) -> None:
        assert _sub("host-test-{count++}", n=0) == "host-test-1"

    def test_plusieurs_occurrences(self) -> None:
        assert _sub("{count++}-host-{count++}") == "4-host-4"

    def test_valeur_sans_masque_inchangee(self) -> None:
        assert _sub("host-fixe") == "host-fixe"


class TestCoexistence:
    def test_la_syntaxe_chevron_marche_toujours(self) -> None:
        # `<N+1>` existait avant : le masque s'ajoute, il ne remplace pas.
        assert _sub("host-<N+1>") == "host-4"

    def test_les_deux_dans_la_meme_valeur(self) -> None:
        assert _sub("<N>-et-{count++}") == "3-et-4"

    def test_ne_touche_pas_aux_placeholders_du_script(self) -> None:
        # `{NODE_NAME}` et consorts sont resolus PLUS TARD, par la substitution
        # des commandes. Les manger ici casserait le script.
        assert _sub("prefixe-{NODE_NAME}") == "prefixe-{NODE_NAME}"

    def test_ne_touche_pas_a_count_sans_increment(self) -> None:
        # `{count}` a la forme d'un placeholder de script : le reserver ici
        # creerait une ambiguite avec `_SUBST_PLACEHOLDER_RE`.
        assert _sub("host-{count}") == "host-{count}"
