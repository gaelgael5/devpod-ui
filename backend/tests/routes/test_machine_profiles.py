"""API des profils de machine.

Deux publics, deux gardes : l'administration decide ce qu'on installe et avec
quels droits ; la lecture est ouverte, puisque c'est l'utilisateur qui choisira
son profil en creant sa machine.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin, require_user
from portal.config.models import MachineProfile
from portal.db.engine import get_conn
from portal.routes import machine_profiles


class _Store:
    """Base simulee : c'est le comportement des routes qu'on teste, pas SQLAlchemy."""

    def __init__(self) -> None:
        self.profils: dict[str, MachineProfile] = {}


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(machine_profiles.router, prefix="/admin")
    app.include_router(machine_profiles.me_router, prefix="/me")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=[])
    app.dependency_overrides[get_conn] = lambda: None

    async def _list(_conn: Any, *, machine_type: str | None = None, **_kw: Any):
        return [
            p
            for p in store.profils.values()
            if machine_type is None or p.machine_type == machine_type
        ]

    async def _upsert(profile: MachineProfile, _conn: Any) -> None:
        store.profils[profile.slug] = profile

    async def _delete(slug: str, _conn: Any) -> bool:
        return store.profils.pop(slug, None) is not None

    monkeypatch.setattr(machine_profiles, "list_profiles", _list)
    monkeypatch.setattr(machine_profiles, "upsert_profile", _upsert)
    monkeypatch.setattr(machine_profiles, "delete_profile", _delete)
    monkeypatch.setattr(machine_profiles, "_require_known_type", lambda _t: None)
    return TestClient(app)


def _corps(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "android-test",
        "label": "Machine Android",
        "hypervisor_type": "proxmox",
        "params": {"MEMORY": "8192"},
        "recipes": [
            {"key": "fe46f7ec-33f7-4252-b29c-cf224b8cd1af", "options": {"avd_ram": "8192"}}
        ],
    }
    base.update(extra)
    return base


class TestAdministration:
    def test_cree_un_profil(self, client: TestClient, store: _Store) -> None:
        res = client.put("/admin/machine-profiles/android-test", json=_corps())

        assert res.status_code == 200
        assert store.profils["android-test"].params == {"MEMORY": "8192"}

    def test_conserve_les_options_de_recette(self, client: TestClient, store: _Store) -> None:
        # C'est tout l'interet : la RAM de l'AVD se decide au profil.
        client.put("/admin/machine-profiles/android-test", json=_corps())

        assert store.profils["android-test"].recipes[0].options == {"avd_ram": "8192"}

    def test_refuse_un_slug_de_corps_different(self, client: TestClient) -> None:
        # Sans ce controle, un PUT ecraserait un profil voisin.
        res = client.put("/admin/machine-profiles/autre", json=_corps())

        assert res.status_code == 422

    def test_refuse_un_type_de_machine_inconnu(self, client: TestClient) -> None:
        res = client.put(
            "/admin/machine-profiles/android-test", json=_corps(machine_type="nimportequoi")
        )

        assert res.status_code == 422

    def test_refuse_deux_fois_la_meme_recette(self, client: TestClient) -> None:
        k = "fe46f7ec-33f7-4252-b29c-cf224b8cd1af"
        res = client.put(
            "/admin/machine-profiles/android-test",
            json=_corps(recipes=[{"key": k}, {"key": k, "options": {"a": "1"}}]),
        )

        assert res.status_code == 422

    def test_supprime(self, client: TestClient, store: _Store) -> None:
        client.put("/admin/machine-profiles/android-test", json=_corps())

        assert client.delete("/admin/machine-profiles/android-test").status_code == 204
        assert store.profils == {}

    def test_supprimer_un_profil_absent(self, client: TestClient) -> None:
        assert client.delete("/admin/machine-profiles/fantome").status_code == 404


class TestLectureUtilisateur:
    def test_liste_les_profils_de_test(self, client: TestClient) -> None:
        client.put("/admin/machine-profiles/android-test", json=_corps())

        res = client.get("/me/machine-profiles")

        assert res.status_code == 200
        assert [p["slug"] for p in res.json()] == ["android-test"]

    def test_masque_les_profils_de_ressources(self, client: TestClient) -> None:
        # Creer une machine de ressources n'existe pas encore : les exposer ici
        # promettrait une action indisponible.
        client.put(
            "/admin/machine-profiles/serveur-rag",
            json=_corps(slug="serveur-rag", machine_type="ressources"),
        )

        assert client.get("/me/machine-profiles").json() == []

    def test_n_expose_pas_les_parametres_figes(self, client: TestClient) -> None:
        # Ils sont decides par l'administrateur ; l'utilisateur choisit un profil,
        # pas une taille de disque.
        client.put("/admin/machine-profiles/android-test", json=_corps())

        assert "params" not in client.get("/me/machine-profiles").json()[0]
