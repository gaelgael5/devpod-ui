"""Application d'une recette sur une machine : compatibilité, préconditions,
idempotence, état.

L'ordre des étapes est le sujet : une précondition non satisfaite doit couper
AVANT le téléchargement, et une recette déjà posée ne doit rien réexécuter.
"""

from __future__ import annotations

import pytest

from portal.recipes.host_apply import (
    HostApplyError,
    apply_recipe_to_host,
    build_state_probe,
    parse_state,
)
from portal.recipes.models import RecipeMeta


def _meta(**extra: object) -> RecipeMeta:
    base: dict[str, object] = {
        "id": "android-emulator",
        "version": "1.2.0",
        "scope": "host",
        "host_usages": ["tests"],
    }
    base.update(extra)
    return RecipeMeta.model_validate(base)


class _Runner:
    """Machine simulée : rejoue des réponses et garde la trace des commandes."""

    def __init__(self, reponses: list[tuple[int, str, str]]) -> None:
        self.reponses = list(reponses)
        self.commandes: list[str] = []

    async def __call__(self, command: str, *, timeout: float = 0) -> tuple[int, str, str]:
        self.commandes.append(command)
        return self.reponses.pop(0) if self.reponses else (0, "", "")


async def _appliquer(
    meta: RecipeMeta, runner: _Runner, *, usage: str = "tests", script: str = "echo ok"
):
    return await apply_recipe_to_host(meta, host_usage=usage, script=script, run=runner)


class TestCompatibilite:
    async def test_refuse_une_famille_non_declaree(self) -> None:
        runner = _Runner([])

        with pytest.raises(HostApplyError, match="famille"):
            await _appliquer(_meta(), runner, usage="workspaces")

        # Rien ne doit partir sur la machine : le refus est local.
        assert runner.commandes == []

    async def test_refuse_une_recette_de_workspace(self) -> None:
        # Le garde-fou qui protège tout le catalogue existant.
        meta = RecipeMeta.model_validate({"id": "outil"})
        runner = _Runner([])

        with pytest.raises(HostApplyError, match="host"):
            await _appliquer(meta, runner)

        assert runner.commandes == []


class TestPreconditions:
    async def test_coupe_avant_tout_telechargement(self) -> None:
        # Le cœur de l'exigence : une recette de 20 Go qui échoue en route
        # laisse la machine à moitié faite.
        meta = _meta(preconditions=[{"path_exists": "/dev/kvm"}])
        runner = _Runner([(0, "PRECOND_FAIL path_exists '/dev/kvm'\n", "")])

        with pytest.raises(HostApplyError, match="/dev/kvm"):
            await _appliquer(meta, runner)

        # Une seule commande : la sonde. Le script n'a jamais été envoyé.
        assert len(runner.commandes) == 1

    async def test_enumere_toutes_les_manquantes(self) -> None:
        meta = _meta(preconditions=[{"path_exists": "/dev/kvm"}, {"disk_free_gb": 25}])
        runner = _Runner(
            [(0, "PRECOND_FAIL path_exists '/dev/kvm'\nPRECOND_FAIL disk_free_gb 25 '/'\n", "")]
        )

        with pytest.raises(HostApplyError) as exc:
            await _appliquer(meta, runner)

        assert "/dev/kvm" in str(exc.value)
        assert "25" in str(exc.value)

    async def test_sans_precondition_on_passe_directement(self) -> None:
        runner = _Runner([(0, "", ""), (0, "", "")])

        await _appliquer(_meta(), runner)

        # Pas de sonde de préconditions : sentinelle puis application.
        assert len(runner.commandes) == 2


class TestIdempotence:
    async def test_ne_rejoue_pas_une_version_deja_posee(self) -> None:
        runner = _Runner([(0, "RECIPE_STATE android-emulator 1.2.0\n", "")])

        res = await _appliquer(_meta(), runner)

        assert res.changed is False
        assert len(runner.commandes) == 1

    async def test_rejoue_quand_la_version_a_change(self) -> None:
        # Une recette versionnée qui évolue doit pouvoir être re-posée.
        runner = _Runner([(0, "RECIPE_STATE android-emulator 1.0.0\n", ""), (0, "", "")])

        res = await _appliquer(_meta(), runner)

        assert res.changed is True

    async def test_pose_la_sentinelle_avec_la_version(self) -> None:
        # Sans version dans la sentinelle, impossible de savoir six mois plus
        # tard ce qui est réellement installé.
        runner = _Runner([(0, "", ""), (0, "", "")])

        await _appliquer(_meta(), runner)

        assert "1.2.0" in runner.commandes[-1]

    async def test_un_echec_ne_pose_pas_la_sentinelle(self) -> None:
        # Sinon la machine se dirait équipée alors que l'installation a échoué,
        # et le re-run suivant ne corrigerait rien.
        runner = _Runner([(0, "", ""), (1, "", "boom")])

        with pytest.raises(HostApplyError, match="boom"):
            await _appliquer(_meta(), runner)


class TestEtat:
    def test_sonde_d_etat_lit_les_sentinelles(self) -> None:
        assert "RECIPE_STATE" in build_state_probe()

    def test_lit_recette_version_et_date(self) -> None:
        etat = parse_state("RECIPE_STATE android-emulator 1.2.0 2026-08-23T20:00:00Z\n")

        assert etat["android-emulator"].version == "1.2.0"
        assert etat["android-emulator"].applied_at == "2026-08-23T20:00:00Z"

    def test_machine_vierge(self) -> None:
        assert parse_state("") == {}

    def test_ignore_le_bruit_du_shell(self) -> None:
        # Bannière SSH, avertissements : le marqueur les distingue.
        etat = parse_state("Welcome\nRECIPE_STATE outil 2.0.0 2026-01-01T00:00:00Z\n")

        assert list(etat) == ["outil"]
