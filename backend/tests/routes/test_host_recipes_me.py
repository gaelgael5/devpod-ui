"""Recettes de host déclenchées par un UTILISATEUR, sur la VM de son workspace.

Ces deux routes déclenchent de l'exécution privilégiée à distance sans exiger le
rôle admin. Leur seule barrière est donc la propriété de la machine, et elle se
vérifie en DEUX temps :

- `_require_ws_and_host` ne contrôle que le WORKSPACE — il valide `host_name` par
  regex sans jamais le rapprocher de quoi que ce soit ;
- `is_owned_test_host` rattache la machine au couple (login, workspace).

Croire que le premier suffisait a ouvert une faille : tout utilisateur pouvait
viser n'importe quelle machine de l'inventaire — celle d'un autre locataire, ou
un nœud du portail — et y faire exécuter une recette avec les droits
d'administration. Le GET était déjà une exécution à distance : la sonde SSH du
catalogue part AVANT tout contrôle de famille.

D'où ces tests : ils échouent si le second contrôle disparaît.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_user
from portal.config.models import HostConfig
from portal.db.engine import get_conn
from portal.recipes.models import RecipeMeta
from portal.routes import host_recipes

#: La machine d'un autre locataire. Elle EXISTE dans l'inventaire global : c'est
#: tout l'intérêt du test — `_load_host` la résout sans filtre de propriétaire.
HOST_ETRANGER = "host-test-999-1"
HOST_A_MOI = "host-test-105-1"


def _host(nom: str) -> HostConfig:
    return HostConfig(name=nom, type="ssh", address="root@10.0.0.1", usage="tests")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(host_recipes.me_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="bob", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: None

    # L'inventaire global ignore la propriété : les deux machines s'y résolvent.
    monkeypatch.setattr(host_recipes, "_load_host", lambda nom: _host(nom))

    async def _require_ws_and_host(ws: str, host_name: str, login: str) -> None:
        """Le vrai : il ne vérifie QUE le workspace. Bob possède `bob-ws`."""
        if ws != "bob-ws":
            raise AssertionError("workspace inattendu dans le test")

    monkeypatch.setattr(
        "portal.routes.test_vm._require_ws_and_host", _require_ws_and_host, raising=False
    )

    async def _est_a_moi(login: str, ws: str, host_name: str, conn: Any) -> bool:
        return (login, ws, host_name) == ("bob", "bob-ws", HOST_A_MOI)

    monkeypatch.setattr(host_recipes, "is_owned_test_host", _est_a_moi)

    async def _catalogue(login: str, conn: Any) -> dict[str, RecipeMeta]:
        return {
            "android-emulator": RecipeMeta.model_validate(
                {"id": "android-emulator", "scope": "host", "host_usages": ["tests"]}
            )
        }

    monkeypatch.setattr(host_recipes, "_load_host_recipes", _catalogue)

    def _jamais(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("aucune connexion ne doit partir vers un host étranger")

    monkeypatch.setattr(host_recipes, "_catalogue_pour_host", _jamais)
    monkeypatch.setattr(host_recipes, "_lancer_application", _jamais)
    return TestClient(app)


def test_lister_les_recettes_d_un_host_etranger_est_refuse(client: TestClient) -> None:
    """Le GET aussi : il sonde la machine en SSH avant tout contrôle de famille."""
    reponse = client.get(f"/me/workspaces/bob-ws/test-hosts/{HOST_ETRANGER}/recipes")

    assert reponse.status_code == 404
    assert HOST_ETRANGER in reponse.json()["detail"]


def test_appliquer_une_recette_sur_un_host_etranger_est_refuse(client: TestClient) -> None:
    reponse = client.post(
        f"/me/workspaces/bob-ws/test-hosts/{HOST_ETRANGER}/recipes/android-emulator"
    )

    assert reponse.status_code == 404
    assert HOST_ETRANGER in reponse.json()["detail"]


def test_un_host_partage_ne_suffit_pas(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """`is_owned_test_host` exige la PROPRIÉTÉ, pas un simple partage.

    Il s'agit d'exécution privilégiée : un workspace à qui la VM est seulement
    partagée n'a pas à y installer quoi que ce soit.
    """

    async def _jamais_proprietaire(login: str, ws: str, host_name: str, conn: Any) -> bool:
        return False

    monkeypatch.setattr(host_recipes, "is_owned_test_host", _jamais_proprietaire)

    reponse = client.post(
        f"/me/workspaces/bob-ws/test-hosts/{HOST_A_MOI}/recipes/android-emulator"
    )

    assert reponse.status_code == 404


def test_sa_propre_machine_passe_le_controle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le garde-fou ne doit pas condamner le cas nominal."""
    vus: dict[str, str] = {}

    async def _catalogue_pour_host(host: HostConfig, login: str, conn: Any) -> dict[str, Any]:
        vus["host"] = host.name
        return {"recipes": []}

    monkeypatch.setattr(host_recipes, "_catalogue_pour_host", _catalogue_pour_host)

    reponse = client.get(f"/me/workspaces/bob-ws/test-hosts/{HOST_A_MOI}/recipes")

    assert reponse.status_code == 200
    assert vus["host"] == HOST_A_MOI
