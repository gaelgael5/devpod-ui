"""Application d'un profil sur une machine fraichement creee."""

from __future__ import annotations

from typing import Any

from portal.config.models import HostConfig, MachineProfile
from portal.profiles.provisioning import apply_profile_recipes
from portal.recipes.models import RecipeMeta

KEY_A = "aaaaaaaa-0000-4000-8000-000000000001"
KEY_B = "bbbbbbbb-0000-4000-8000-000000000002"


def _host() -> HostConfig:
    return HostConfig(name="host-test-1", type="ssh", address="root@10.0.0.1", usage="tests")


def _meta(recipe_id: str, key: str) -> RecipeMeta:
    return RecipeMeta.model_validate(
        {"id": recipe_id, "key": key, "scope": "host", "host_usages": ["tests"]}
    )


def _profil(recipes: list[dict[str, Any]]) -> MachineProfile:
    return MachineProfile.model_validate(
        {
            "slug": "p1",
            "label": "P1",
            "hypervisor_type": "proxmox",
            "recipes": recipes,
        }
    )


class _Runner:
    """Machine simulee. `echecs` nomme les scripts qui doivent echouer."""

    def __init__(self, echecs: set[str] | None = None) -> None:
        self.echecs = echecs or set()
        self.appels: list[str] = []

    async def __call__(self, command: str, *, timeout: float = 0) -> tuple[int, str, str]:
        self.appels.append(command)
        if any(marque in command for marque in self.echecs):
            return 1, "", "boom"
        return 0, "", ""


async def _lignes(profil: MachineProfile, catalogue: dict[str, RecipeMeta], runner: _Runner):
    return [
        ligne
        async for ligne in apply_profile_recipes(
            profil,
            host=_host(),
            catalogue=catalogue,
            run=runner,
            read_script=lambda rid: f"echo {rid}",
        )
    ]


class TestOrdre:
    async def test_applique_dans_l_ordre_declare(self) -> None:
        # Une dependance se pose avant celle qui l'utilise.
        catalogue = {"a": _meta("a-outil", KEY_A), "b": _meta("b-outil", KEY_B)}
        profil = _profil([{"key": KEY_B}, {"key": KEY_A}])

        lignes = await _lignes(profil, catalogue, _Runner())

        assert lignes[0].startswith("==> Recette b-outil")
        assert any(ligne.startswith("==> Recette a-outil") for ligne in lignes[1:])

    async def test_sans_recette_ne_produit_rien(self) -> None:
        assert await _lignes(_profil([]), {}, _Runner()) == []


class TestOptions:
    async def test_transmet_les_options_du_profil(self) -> None:
        # L'AVD, la RAM, le niveau d'API se decident au profil.
        meta = RecipeMeta.model_validate(
            {
                "id": "android",
                "key": KEY_A,
                "scope": "host",
                "host_usages": ["tests"],
                "options": {"avd_ram": {"default": "4096"}},
            }
        )
        runner = _Runner()
        profil = _profil([{"key": KEY_A, "options": {"avd_ram": "8192"}}])

        await _lignes(profil, {"android": meta}, runner)

        assert any("RECIPE_OPT_AVD_RAM=8192" in appel for appel in runner.appels)


class TestResilience:
    async def test_un_echec_n_interrompt_pas_la_suite(self) -> None:
        # La machine est creee : une recette en echec ne doit pas priver
        # l'utilisateur des suivantes.
        catalogue = {"a": _meta("a-outil", KEY_A), "b": _meta("b-outil", KEY_B)}
        profil = _profil([{"key": KEY_A}, {"key": KEY_B}])
        runner = _Runner(echecs={"a-outil"})

        lignes = await _lignes(profil, catalogue, runner)

        assert any("ECHEC de la recette a-outil" in ligne for ligne in lignes)
        assert any("b-outil posee" in ligne for ligne in lignes)

    async def test_recette_disparue_du_catalogue(self) -> None:
        # Retiree depuis la creation du profil : on le dit, le reste garde son sens.
        profil = _profil([{"key": KEY_A}])

        lignes = await _lignes(profil, {}, _Runner())

        assert len(lignes) == 1
        assert "absente du catalogue" in lignes[0]

    async def test_recette_sans_script(self) -> None:
        profil = _profil([{"key": KEY_A}])
        lignes = [
            ligne
            async for ligne in apply_profile_recipes(
                profil,
                host=_host(),
                catalogue={"a": _meta("a-outil", KEY_A)},
                run=_Runner(),
                read_script=lambda _rid: None,
            )
        ]

        assert "sans install.sh" in lignes[0]


class TestIdempotence:
    async def test_dit_quand_rien_n_a_change(self) -> None:
        # Sentinelle deja posee dans cette version : le message doit le refleter,
        # sinon on croit avoir reinstalle 20 Go.
        meta = _meta("android", KEY_A)
        runner = _Runner()

        async def deja_pose(command: str, *, timeout: float = 0) -> tuple[int, str, str]:
            runner.appels.append(command)
            if "RECIPE_STATE" in command:
                return 0, f"RECIPE_STATE android {meta.version}\n", ""
            return 0, "", ""

        lignes = [
            ligne
            async for ligne in apply_profile_recipes(
                _profil([{"key": KEY_A}]),
                host=_host(),
                catalogue={"android": meta},
                run=deja_pose,
                read_script=lambda rid: f"echo {rid}",
            )
        ]

        assert any("deja presente" in ligne for ligne in lignes)
