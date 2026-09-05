"""L'adresse de facturation, vue de son titulaire.

Le test qui compte : **aucune adresse dans les journaux** — vérifié en
capturant les logs de la mutation, pas supposé. Une adresse n'est pas un secret
au sens du résolveur, la redaction automatique ne la couvre pas.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog.testing
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_user
from portal.billing.adresse import AdresseFacturation
from portal.db.engine import get_conn
from portal.routes import billing_address as routes


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="bob", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {"adresses": {}}

    async def _poser(login: str, adresse: AdresseFacturation, _conn: Any) -> None:
        etat["adresses"][login] = adresse

    async def _lire(login: str, _conn: Any) -> AdresseFacturation | None:
        return etat["adresses"].get(login)

    monkeypatch.setattr(routes, "poser_adresse", _poser)
    monkeypatch.setattr(routes, "lire_adresse", _lire)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


CORPS = {
    "line1": "12 rue des Lilas",
    "line2": "",
    "city": "Lyon",
    "postal_code": "69003",
    "state": "",
    "country": "FR",
}


def test_poser_puis_relire_sa_propre_adresse(client: TestClient) -> None:
    assert client.put("/me/billing-address", json=CORPS).status_code == 200

    assert client.get("/me/billing-address").json() == CORPS


def test_sans_adresse_le_compte_rend_null(client: TestClient) -> None:
    assert client.get("/me/billing-address").json() is None


def test_un_pays_mal_forme_est_refuse(client: TestClient) -> None:
    assert client.put("/me/billing-address", json={**CORPS, "country": "fr"}).status_code == 422


def test_aucune_adresse_dans_les_journaux(client: TestClient) -> None:
    """La DoD de la fiche : vérifié, pas supposé. Seul le pays — qui pilote la
    taxe — a le droit d'apparaître."""
    with structlog.testing.capture_logs() as journaux:
        client.put("/me/billing-address", json=CORPS)

    rendu = repr(journaux)
    for morceau in ("Lilas", "Lyon", "69003"):
        assert morceau not in rendu, morceau


def test_le_modele_lui_meme_masque_l_adresse() -> None:
    """Défense en profondeur : un log accidentel du MODÈLE ne fuit que le pays."""
    adresse = AdresseFacturation.model_validate(CORPS)

    for rendu in (repr(adresse), str(adresse), f"{adresse}"):
        assert "Lilas" not in rendu
        assert "FR" in rendu
