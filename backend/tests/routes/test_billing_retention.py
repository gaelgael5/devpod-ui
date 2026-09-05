"""L'API d'action de rétention, vue des automates.

C'est la route qui DÉTRUIT : ces tests verrouillent surtout ce qu'elle ne doit
pas faire — toucher un autre host que celui demandé, toucher les workspaces
d'un autre compte, abandonner le lot au premier échec, ou détruire sans
archiver (`shelve`).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin, require_admin_or_api_key
from portal.config.models import GlobalConfig
from portal.db.engine import get_conn
from portal.routes import billing_retention as routes


class _ServiceTemoin:
    def __init__(self, etat: dict[str, Any]) -> None:
        self._etat = etat

    async def stop(self, *, login: str, ws_id: str) -> None:
        if ws_id in self._etat["en_panne"]:
            raise RuntimeError("host injoignable")
        self._etat["arrets"].append((login, ws_id))

    async def delete(self, *, login: str, ws_id: str, shelve: bool) -> dict[str, Any]:
        if ws_id in self._etat["en_panne"]:
            raise RuntimeError("host injoignable")
        self._etat["suppressions"].append((login, ws_id, shelve))
        return {}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/admin")
    app.dependency_overrides[require_admin_or_api_key] = lambda: UserInfo(
        login="__api__", roles=["admin"]
    )
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {
        "comptes": {"bob"},
        "workspaces": [
            {"ws_id": "bob-alpha", "login": "bob", "host_name": "ded-101"},
            {"ws_id": "bob-beta", "login": "bob", "host_name": "ded-101"},
            {"ws_id": "bob-ailleurs", "login": "bob", "host_name": "mut-200"},
        ],
        "arrets": [],
        "suppressions": [],
        "en_panne": set(),
    }

    async def _user_exists_db(login: str, _conn: Any) -> bool:
        return login in etat["comptes"]

    async def _list_by_login_db(login: str, _conn: Any) -> list[dict[str, Any]]:
        return [w for w in etat["workspaces"] if w["login"] == login]

    monkeypatch.setattr(routes, "user_exists_db", _user_exists_db)
    monkeypatch.setattr(routes, "list_by_login_db", _list_by_login_db)
    monkeypatch.setattr(routes, "_service", lambda: _ServiceTemoin(etat))

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def _corps(**extra: Any) -> dict[str, Any]:
    return {
        "action": "arreter",
        "type_hebergement": "dedie",
        "user_id": "bob",
        "host_id": "ded-101",
        **extra,
    }


def test_arreter_stoppe_les_workspaces_du_host_et_eux_seuls(client: TestClient) -> None:
    reponse = client.post("/admin/billing/retention/action", json=_corps())

    assert reponse.status_code == 200
    assert [r["statut"] for r in reponse.json()["resultats"]] == ["arrete", "arrete"]
    assert client.etat["arrets"] == [("bob", "bob-alpha"), ("bob", "bob-beta")]  # type: ignore[attr-defined]
    # `bob-ailleurs` vit sur un autre host : il n'est pas concerné.


def test_detruire_archive_avant_de_supprimer(client: TestClient) -> None:
    """`shelve=True` systématique : le travail en attente part sur le remote
    git AVANT la destruction — l'issue « archiver » de la fiche."""
    client.post("/admin/billing/retention/action", json=_corps(action="detruire"))

    assert client.etat["suppressions"] == [  # type: ignore[attr-defined]
        ("bob", "bob-alpha", True),
        ("bob", "bob-beta", True),
    ]


def test_un_echec_n_abandonne_pas_le_lot(client: TestClient) -> None:
    client.etat["en_panne"] = {"bob-alpha"}  # type: ignore[attr-defined]

    reponse = client.post("/admin/billing/retention/action", json=_corps(action="detruire"))

    resultats = {r["ws_id"]: r["statut"] for r in reponse.json()["resultats"]}
    assert resultats == {"bob-alpha": "echec", "bob-beta": "detruit"}


def test_un_compte_inconnu_rend_404_sans_rien_toucher(client: TestClient) -> None:
    reponse = client.post("/admin/billing/retention/action", json=_corps(user_id="fantome"))

    assert reponse.status_code == 404
    assert client.etat["arrets"] == []  # type: ignore[attr-defined]


def test_un_host_sans_workspace_rend_un_lot_vide(client: TestClient) -> None:
    """Idempotence du script : rejouer l'action après destruction ne casse rien."""
    reponse = client.post("/admin/billing/retention/action", json=_corps(host_id="ded-999"))

    assert reponse.status_code == 200
    assert reponse.json()["resultats"] == []


def test_une_action_inconnue_est_refusee(client: TestClient) -> None:
    assert (
        client.post("/admin/billing/retention/action", json=_corps(action="formater")).status_code
        == 422
    )


# ─── Les délais réglables ────────────────────────────────────────────────────


@pytest.fixture
def client_config(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="root", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    cfg = GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {"external_url": "https://x", "base_domain": "x"},
            "auth": {"oidc": {"issuer": "", "client_id": "", "client_secret": ""}},
        }
    )
    sauvegardes: list[GlobalConfig] = []

    async def _save(nouvelle: GlobalConfig, _conn: Any) -> None:
        sauvegardes.append(nouvelle)

    monkeypatch.setattr(routes, "load_global", lambda: cfg)
    monkeypatch.setattr(routes, "save_global_db", _save)
    monkeypatch.setattr(routes, "set_cached_global", lambda c: None)

    client = TestClient(app)
    client.sauvegardes = sauvegardes  # type: ignore[attr-defined]
    return client


def test_les_delais_par_defaut_sont_servis(client_config: TestClient) -> None:
    corps = client_config.get("/admin/billing/retention/config").json()

    assert corps == {"echec_paiement_jours": 14, "resiliation_jours": 30}


def test_les_delais_se_reglent(client_config: TestClient) -> None:
    reponse = client_config.put(
        "/admin/billing/retention/config",
        json={"echec_paiement_jours": 7, "resiliation_jours": 60},
    )

    assert reponse.status_code == 200
    (sauve,) = client_config.sauvegardes  # type: ignore[attr-defined]
    assert sauve.billing.retention.resiliation_jours == 60


def test_un_delai_nul_est_refuse(client_config: TestClient) -> None:
    """Zéro jour = destruction à la première passe, sans fenêtre pour archiver."""
    reponse = client_config.put(
        "/admin/billing/retention/config",
        json={"echec_paiement_jours": 0, "resiliation_jours": 30},
    )

    assert reponse.status_code == 422
    assert client_config.sauvegardes == []  # type: ignore[attr-defined]
