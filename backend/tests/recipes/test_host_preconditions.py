"""Préconditions d'une recette de host, vérifiées AVANT tout téléchargement.

Une recette de host pèse parfois 20 Go (chaîne Android). Échouer après 2 Go
téléchargés est inacceptable : ce qui peut être su d'avance doit l'être, et le
message doit dire LAQUELLE des préconditions manque.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.recipes.host_preconditions import build_check_command, parse_check_output
from portal.recipes.models import RecipeMeta, RecipePrecondition


def _pre(**kw: object) -> RecipePrecondition:
    return RecipePrecondition.model_validate(kw)


class TestDeclaration:
    def test_chemin_relatif_refuse(self) -> None:
        # Un chemin relatif dépend du répertoire courant du shell distant :
        # la vérification ne voudrait plus rien dire.
        with pytest.raises(ValidationError):
            _pre(path_exists="dev/kvm")

    def test_metacaracteres_shell_refuses(self) -> None:
        # La valeur vient du catalogue, mais elle finit dans une commande
        # distante privilégiée : on ne lui fait pas confiance sur parole.
        with pytest.raises(ValidationError):
            _pre(path_exists="/dev/kvm; rm -rf /")

    def test_disque_negatif_refuse(self) -> None:
        with pytest.raises(ValidationError):
            _pre(disk_free_gb=-1, disk_path="/")

    def test_precondition_vide_refusee(self) -> None:
        # Une précondition qui ne vérifie rien passerait toujours : c'est une
        # fausse garantie, pire que pas de garantie du tout.
        with pytest.raises(ValidationError, match="at least one"):
            _pre()

    def test_architecture_libre_mais_bornee(self) -> None:
        assert _pre(arch="x86_64").arch == "x86_64"
        with pytest.raises(ValidationError):
            _pre(arch="x86_64 || true")


class TestCommande:
    def test_sans_precondition_aucune_commande(self) -> None:
        assert build_check_command([]) == ""

    def test_teste_la_presence_d_un_chemin(self) -> None:
        cmd = build_check_command([_pre(path_exists="/dev/kvm")])

        assert "/dev/kvm" in cmd

    def test_teste_l_espace_disque(self) -> None:
        cmd = build_check_command([_pre(disk_free_gb=20, disk_path="/var")])

        assert "/var" in cmd
        # 20 Go exprimés en blocs de 1 Ko : c'est l'unité de `df -kP`.
        assert str(20 * 1024 * 1024) in cmd

    def test_quote_les_valeurs(self) -> None:
        # Même issues du catalogue, elles sont quotées : une regex qui laisserait
        # passer un caractère inattendu ne doit pas devenir une injection.
        cmd = build_check_command([_pre(path_exists="/opt/android sdk")])

        assert "'/opt/android sdk'" in cmd


class TestResultat:
    def test_aucune_sortie_vaut_succes(self) -> None:
        assert parse_check_output("") == []

    def test_remonte_la_precondition_manquante(self) -> None:
        manquantes = parse_check_output("PRECOND_FAIL path_exists /dev/kvm\n")

        assert len(manquantes) == 1
        assert "/dev/kvm" in manquantes[0]

    def test_remonte_toutes_les_manquantes(self) -> None:
        # Une seule à la fois obligerait l'admin à recommencer autant de fois
        # qu'il manque de choses.
        manquantes = parse_check_output(
            "PRECOND_FAIL path_exists /dev/kvm\nPRECOND_FAIL disk_free_gb 20 /var\n"
        )

        assert len(manquantes) == 2

    def test_ignore_le_bruit(self) -> None:
        # Le shell distant peut écrire ses propres lignes (bannière, warning ssh).
        assert parse_check_output("Welcome to Debian\nPRECOND_FAIL arch x86_64\n") == [
            m for m in parse_check_output("PRECOND_FAIL arch x86_64\n")
        ]


class TestIntegrationMeta:
    def test_une_recette_porte_ses_preconditions(self) -> None:
        meta = RecipeMeta.model_validate(
            {
                "id": "android-emulator",
                "scope": "host",
                "host_usages": ["tests"],
                "preconditions": [{"path_exists": "/dev/kvm"}, {"disk_free_gb": 25}],
            }
        )

        assert len(meta.preconditions) == 2

    def test_preconditions_interdites_hors_scope_host(self) -> None:
        # Elles ne seraient jamais vérifiées : la déclaration serait trompeuse.
        with pytest.raises(ValidationError, match="scope"):
            RecipeMeta.model_validate(
                {"id": "outil", "preconditions": [{"path_exists": "/dev/kvm"}]}
            )
