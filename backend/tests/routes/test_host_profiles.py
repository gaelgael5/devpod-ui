"""API des profils de host.

Un profil de host choisit un profil de machine et VALUE les variables declarees
par le type d'hyperviseur — dont `capacity_workspaces`, le nombre de workspaces
que la machine tient sans planter.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.config.models import HostProfile, HypervisorType, MachineProfile
from portal.db.engine import get_conn
from portal.routes import host_profiles

MACHINE = MachineProfile(
    slug="host-workspace-standard",
    label="Host workspace standard",
    machine_type="workspaces",
    hypervisor_type="proxmox4vm",
    params={"MEMORY": "16384"},
)

TYPE = HypervisorType(
    name="proxmox4vm",
    label="Proxmox 4 VM",
    variables=[
        {"label": "Capacité en workspaces", "slug": "capacity_workspaces", "type": "int"},
        {"label": "Zone", "slug": "zone", "type": "string"},
    ],
)


class _Store:
    """Base simulee : c'est le comportement des routes qu'on teste."""

    def __init__(self) -> None:
        self.profils: dict[str, HostProfile] = {}
        self.machines: dict[str, MachineProfile] = {MACHINE.slug: MACHINE}


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(host_profiles.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    async def _list(_conn: Any, **_kw: Any) -> list[HostProfile]:
        return list(store.profils.values())

    async def _get(slug: str, _conn: Any) -> HostProfile | None:
        return store.profils.get(slug)

    async def _upsert(profile: HostProfile, _conn: Any) -> None:
        store.profils[profile.slug] = profile

    async def _delete(slug: str, _conn: Any) -> bool:
        return store.profils.pop(slug, None) is not None

    async def _machine(slug: str, _conn: Any) -> MachineProfile | None:
        return store.machines.get(slug)

    monkeypatch.setattr(host_profiles, "list_host_profiles", _list)
    monkeypatch.setattr(host_profiles, "get_host_profile", _get)
    monkeypatch.setattr(host_profiles, "upsert_host_profile", _upsert)
    monkeypatch.setattr(host_profiles, "delete_host_profile", _delete)
    monkeypatch.setattr(host_profiles, "get_profile", _machine)
    monkeypatch.setattr(host_profiles, "_variables_declarees", lambda _m: list(TYPE.variables))
    return TestClient(app)


def _corps(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "ws-standard",
        "label": "Workspaces standard",
        "machine_profile": "host-workspace-standard",
        "variables": {"capacity_workspaces": "8", "zone": "pve2"},
    }
    base.update(extra)
    return base


def test_cree_un_profil_de_host(client: TestClient, store: _Store) -> None:
    res = client.put("/admin/host-profiles/ws-standard", json=_corps())

    assert res.status_code == 200
    assert store.profils["ws-standard"].variables["capacity_workspaces"] == "8"


def test_la_capacite_se_lit_en_entier(client: TestClient, store: _Store) -> None:
    # C'est tout l'interet : le portail doit savoir combien de workspaces
    # la machine tient sans planter.
    client.put("/admin/host-profiles/ws-standard", json=_corps())

    assert store.profils["ws-standard"].capacity_workspaces() == 8


def test_une_capacite_non_renseignee_ne_vaut_pas_illimitee(client: TestClient) -> None:
    profil = HostProfile(slug="x", label="X", machine_profile="m")
    assert profil.capacity_workspaces() is None


def test_refuse_une_variable_non_declaree(client: TestClient) -> None:
    # Faute de frappe ou variable retiree du type : on le dit a la saisie, pas
    # a la creation de la machine.
    res = client.put(
        "/admin/host-profiles/ws-standard",
        json=_corps(variables={"capacity_workspace": "8"}),
    )

    assert res.status_code == 422
    assert "capacity_workspace" in res.json()["detail"]


def test_refuse_un_entier_mal_saisi(client: TestClient) -> None:
    res = client.put(
        "/admin/host-profiles/ws-standard",
        json=_corps(variables={"capacity_workspaces": "beaucoup"}),
    )

    assert res.status_code == 422
    assert "entier" in res.json()["detail"]


def test_accepte_une_chaine_libre_sur_une_variable_texte(client: TestClient, store: _Store) -> None:
    client.put("/admin/host-profiles/ws-standard", json=_corps(variables={"zone": "pve2"}))

    assert store.profils["ws-standard"].variables == {"zone": "pve2"}


def test_normalise_les_espaces_autour_des_valeurs(client: TestClient, store: _Store) -> None:
    client.put(
        "/admin/host-profiles/ws-standard",
        json=_corps(variables={"capacity_workspaces": "  8  "}),
    )

    assert store.profils["ws-standard"].variables["capacity_workspaces"] == "8"


def test_refuse_un_profil_de_machine_inconnu(client: TestClient) -> None:
    res = client.put("/admin/host-profiles/ws-standard", json=_corps(machine_profile="fantome"))

    assert res.status_code == 422
    assert "fantome" in res.json()["detail"]


def test_refuse_un_slug_de_corps_different(client: TestClient) -> None:
    # Sans cette garde, un PUT ecraserait un profil voisin.
    res = client.put("/admin/host-profiles/autre", json=_corps())

    assert res.status_code == 422


def test_liste_les_profils(client: TestClient) -> None:
    client.put("/admin/host-profiles/ws-standard", json=_corps())

    res = client.get("/admin/host-profiles")

    assert [p["slug"] for p in res.json()] == ["ws-standard"]


def test_supprime_un_profil(client: TestClient, store: _Store) -> None:
    client.put("/admin/host-profiles/ws-standard", json=_corps())

    assert client.delete("/admin/host-profiles/ws-standard").status_code == 204
    assert store.profils == {}


def test_supprimer_un_profil_absent_est_un_404(client: TestClient) -> None:
    assert client.delete("/admin/host-profiles/fantome").status_code == 404


def test_expose_les_variables_a_renseigner(client: TestClient) -> None:
    # L'IHM construit son formulaire a partir de la declaration du type, elle
    # ne fige pas la liste dans le code.
    res = client.get("/admin/host-profiles/variables/host-workspace-standard")

    assert [v["slug"] for v in res.json()] == ["capacity_workspaces", "zone"]
    assert res.json()[0]["type"] == "int"


def test_les_variables_d_un_profil_de_machine_inconnu_sont_un_422(client: TestClient) -> None:
    assert client.get("/admin/host-profiles/variables/fantome").status_code == 422
