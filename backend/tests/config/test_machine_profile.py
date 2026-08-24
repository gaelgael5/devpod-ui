"""Profil de machine : parametres figes + recettes a poser, sous un slug.

Remplace le jeu unique `test_host_params` du type d'hyperviseur. Une machine
creee garde la reference du profil utilise — sans elle, impossible de savoir
six mois plus tard avec quoi elle a ete montee.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.config.models import MachineProfile, ProfileRecipe


def _profil(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "android-test",
        "label": "Machine de test Android",
        "hypervisor_type": "proxmox",
    }
    base.update(extra)
    return base


class TestIdentite:
    def test_defauts(self) -> None:
        p = MachineProfile.model_validate(_profil())

        assert p.machine_type == "test"
        assert p.params == {}
        assert p.recipes == []

    def test_slug_normalise_le_nommage(self) -> None:
        # Le slug sert d'identifiant stable et voyage en URL.
        with pytest.raises(ValidationError):
            MachineProfile.model_validate(_profil(slug="Android Test"))

    def test_label_obligatoire(self) -> None:
        # Le slug est technique ; c'est le label que l'utilisateur choisit.
        with pytest.raises(ValidationError):
            MachineProfile.model_validate(_profil(label=""))

    def test_type_de_machine_borne(self) -> None:
        assert MachineProfile.model_validate(_profil(machine_type="ressources")).machine_type == (
            "ressources"
        )
        with pytest.raises(ValidationError):
            MachineProfile.model_validate(_profil(machine_type="nimportequoi"))

    def test_type_hyperviseur_obligatoire(self) -> None:
        # Les parametres n'ont de sens que contre la spec d'un type donne.
        with pytest.raises(ValidationError):
            MachineProfile.model_validate(_profil(hypervisor_type=""))


class TestRecettes:
    def test_une_recette_porte_ses_options(self) -> None:
        # Choisir une recette sans pouvoir la parametrer n'aurait pas de sens :
        # l'AVD, la RAM, le niveau d'API se decident au profil.
        p = MachineProfile.model_validate(
            _profil(
                recipes=[
                    {
                        "key": "fe46f7ec-33f7-4252-b29c-cf224b8cd1af",
                        "options": {"avd_ram": "8192"},
                    }
                ]
            )
        )

        assert p.recipes[0].options == {"avd_ram": "8192"}

    def test_recette_sans_option(self) -> None:
        p = MachineProfile.model_validate(
            _profil(recipes=[{"key": "fe46f7ec-33f7-4252-b29c-cf224b8cd1af"}])
        )

        assert p.recipes[0].options == {}

    def test_cle_de_recette_est_un_uuid(self) -> None:
        # On reference par `key`, pas par `id` : un id se renomme au catalogue,
        # la key survit. C'est deja ce que fait `installs_after`.
        with pytest.raises(ValidationError):
            ProfileRecipe.model_validate({"key": "android-emulator"})

    def test_ordre_conserve(self) -> None:
        # Les recettes s'appliquent dans l'ordre declare : une dependance posee
        # avant celle qui l'utilise.
        keys = [
            "aaaaaaaa-0000-4000-8000-000000000001",
            "bbbbbbbb-0000-4000-8000-000000000002",
        ]
        p = MachineProfile.model_validate(_profil(recipes=[{"key": k} for k in keys]))

        assert [r.key for r in p.recipes] == keys

    def test_refuse_deux_fois_la_meme_recette(self) -> None:
        # Deux entrees pour une meme recette avec des options differentes : la
        # derniere gagnerait en silence.
        k = "fe46f7ec-33f7-4252-b29c-cf224b8cd1af"
        with pytest.raises(ValidationError, match="doublon|duplicate"):
            MachineProfile.model_validate(
                _profil(recipes=[{"key": k, "options": {"a": "1"}}, {"key": k}])
            )
