"""La connexion Listmonk : configuration référencée, test authentifié.

Ce que ces tests verrouillent : la clef n'est jamais stockée (seul son slug),
activer sans contrat complet est refusé, et « Tester la connexion » exerce un
appel AUTHENTIFIÉ — le faux positif du `GET /` qui répond 200 sans clef est
exactement le piège déjà payé sur le producteur d'événements (bug 90cfaca8).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.config.models import ListmonkConfig
from portal.db.engine import get_conn
from portal.routes import listmonk as routes


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="root", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {
        "config": ListmonkConfig(
            enabled=True, url="https://listmonk.example", apikey_secret="listmonk-api"
        ),
        "secrets": {"listmonk-api": "api_user:jeton"},
        "sauvegardes": [],
    }

    class _Global:
        @property
        def listmonk(self) -> ListmonkConfig:
            return etat["config"]

        @listmonk.setter
        def listmonk(self, valeur: ListmonkConfig) -> None:
            etat["config"] = valeur

    async def _save(cfg: Any, _conn: Any) -> None:
        etat["sauvegardes"].append(cfg.listmonk)

    async def _reveal(slug: str, _conn: Any) -> str:
        if slug not in etat["secrets"]:
            raise KeyError(slug)
        return str(etat["secrets"][slug])

    monkeypatch.setattr(routes, "load_global", lambda: _Global())
    monkeypatch.setattr(routes, "save_global_db", _save)
    monkeypatch.setattr(routes, "set_cached_global", lambda c: None)
    monkeypatch.setattr(routes, "reveal_system_secret", _reveal)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def test_la_config_servie_ne_porte_que_le_slug(client: TestClient) -> None:
    corps = client.get("/admin/listmonk").json()

    assert corps == {
        "enabled": True,
        "url": "https://listmonk.example",
        "apikey_secret": "listmonk-api",
    }
    assert "jeton" not in str(corps)


def test_activer_sans_contrat_complet_est_refuse(client: TestClient) -> None:
    """Fail closed : activé sans URL ou sans clef, rien ne partirait — autant
    refuser à la saisie qu'échouer au premier envoi."""
    reponse = client.put(
        "/admin/listmonk",
        json={"enabled": True, "url": "", "apikey_secret": "listmonk-api"},
    )

    assert reponse.status_code == 422
    assert client.etat["sauvegardes"] == []  # type: ignore[attr-defined]


def test_l_url_est_normalisee_sans_slash_final(client: TestClient) -> None:
    reponse = client.put(
        "/admin/listmonk",
        json={"enabled": True, "url": "https://lm.example/", "apikey_secret": "listmonk-api"},
    )

    assert reponse.json()["url"] == "https://lm.example"


def test_desactive_se_sauve_sans_contrainte(client: TestClient) -> None:
    reponse = client.put(
        "/admin/listmonk", json={"enabled": False, "url": "", "apikey_secret": ""}
    )

    assert reponse.status_code == 200


@respx.mock
def test_le_test_exerce_un_appel_authentifie(client: TestClient) -> None:
    """Le cœur : la requête porte la clef, sur un endpoint qui la VÉRIFIE."""
    route = respx.get("https://listmonk.example/api/lists").mock(
        return_value=httpx.Response(200, json={"data": {"results": []}})
    )

    corps = client.post("/admin/listmonk/test-connection").json()

    assert corps["ok"] is True
    assert route.calls.last.request.headers["Authorization"] == "token api_user:jeton"


@respx.mock
def test_une_clef_fausse_echoue_et_le_dit(client: TestClient) -> None:
    respx.get("https://listmonk.example/api/lists").mock(
        return_value=httpx.Response(403, json={"message": "invalid API credentials"})
    )

    corps = client.post("/admin/listmonk/test-connection").json()

    assert corps["ok"] is False
    assert corps["status_code"] == 403
    assert corps["motif"] == "invalid API credentials"


@respx.mock
def test_une_instance_injoignable_est_une_issue_distincte(client: TestClient) -> None:
    respx.get("https://listmonk.example/api/lists").mock(side_effect=httpx.ConnectError("boom"))

    corps = client.post("/admin/listmonk/test-connection").json()

    assert corps["ok"] is False
    assert corps["status_code"] is None
    assert "injoignable" in corps["motif"]


def test_un_slug_qui_ne_resout_plus_se_dit_au_test(client: TestClient) -> None:
    """Pas au premier envoi, sous la forme d'un « secret introuvable » sans
    rapport apparent avec ce qu'on venait de régler."""
    client.etat["secrets"] = {}  # type: ignore[attr-defined]

    corps = client.post("/admin/listmonk/test-connection").json()

    assert corps["ok"] is False
    assert "introuvable" in corps["motif"]


def test_sans_configuration_le_test_est_refuse(client: TestClient) -> None:
    client.etat["config"] = ListmonkConfig()  # type: ignore[attr-defined]

    assert client.post("/admin/listmonk/test-connection").status_code == 409
