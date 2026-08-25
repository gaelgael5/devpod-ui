"""Application d'un profil sur une machine fraichement creee."""

from __future__ import annotations

from typing import Any

from portal.config.models import HostConfig, MachineProfile
from portal.profiles.provisioning import apply_profile_recipes, deploy_profile_services
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


class TestServices:
    """Services Docker declares par le profil, demarres apres la creation."""

    @staticmethod
    def _profil_services(services: list[dict[str, Any]]) -> MachineProfile:
        return MachineProfile.model_validate(
            {
                "slug": "p1",
                "label": "P1",
                "hypervisor_type": "proxmox",
                "services": services,
            }
        )

    async def _lignes(
        self,
        profil: MachineProfile,
        templates: dict[str, object],
        *,
        deja: set[str] | None = None,
        echecs: set[str] | None = None,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        poses: list[dict[str, Any]] = []
        deja = deja or set()
        echecs = echecs or set()

        async def _deploy(**kwargs: Any) -> None:
            if kwargs["name"] in echecs:
                raise RuntimeError("port occupe")
            poses.append(kwargs)

        async def _deja(nom: str) -> bool:
            return nom in deja

        lignes = [
            ligne
            async for ligne in deploy_profile_services(
                profil,
                host=_host(),
                templates=templates,
                deploy=_deploy,
                already_deployed=_deja,
            )
        ]
        return lignes, poses

    async def test_demarre_dans_l_ordre_declare(self) -> None:
        # Un collecteur peut devoir demarrer avant ce qu'il observe.
        profil = self._profil_services(
            [{"template_id": "alloy-collector"}, {"template_id": "searxng"}]
        )

        _lignes, poses = await self._lignes(
            profil, {"alloy-collector": object(), "searxng": object()}
        )

        assert [p["name"] for p in poses] == ["alloy-collector", "searxng"]

    async def test_transmet_les_parametres_du_profil(self) -> None:
        profil = self._profil_services([{"template_id": "searxng", "params": {"PORT": "8081"}}])

        _lignes, poses = await self._lignes(profil, {"searxng": object()})

        assert poses[0]["env_values"] == {"PORT": "8081"}

    async def test_ne_redeploie_pas_un_service_present(self) -> None:
        # Idempotence : ne rien faire, pas ecraser — meme regle que l'auto-start.
        profil = self._profil_services([{"template_id": "searxng"}])

        lignes, poses = await self._lignes(profil, {"searxng": object()}, deja={"searxng"})

        assert poses == []
        assert any("deja deploye" in ligne for ligne in lignes)

    async def test_un_echec_n_interrompt_pas_la_suite(self) -> None:
        profil = self._profil_services(
            [{"template_id": "searxng"}, {"template_id": "alloy-collector"}]
        )

        lignes, poses = await self._lignes(
            profil, {"searxng": object(), "alloy-collector": object()}, echecs={"searxng"}
        )

        assert any("ECHEC du service searxng" in ligne for ligne in lignes)
        assert [p["name"] for p in poses] == ["alloy-collector"]

    async def test_template_disparu_de_la_galerie(self) -> None:
        profil = self._profil_services([{"template_id": "searxng"}])

        lignes, poses = await self._lignes(profil, {})

        assert poses == []
        assert "absent de la galerie" in lignes[0]

    async def test_sans_service_ne_produit_rien(self) -> None:
        lignes, _ = await self._lignes(self._profil_services([]), {})

        assert lignes == []
