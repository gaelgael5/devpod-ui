"""Capacité d'accueil et provenance d'un host, vues de l'API d'administration.

Ces deux données décident de ce que le portail peut poser sur une machine :
combien de workspaces elle tient, et si le pool mutualisé a le droit de la
remplir. Le handler d'update reconstruit un `HostConfig` champ par champ — tout
champ qu'il oublie est SILENCIEUSEMENT remis à sa valeur par défaut. C'est
exactement ce qui est arrivé à `profile_slug`, déclaré depuis les profils de
host et jamais persisté.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from portal.auth.rbac import UserInfo, require_admin
from portal.config.models import GlobalConfig, HostConfig
from portal.db.engine import get_conn
from portal.routes import admin


def _config(host: HostConfig) -> GlobalConfig:
    return GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {"base_domain": "dev.yoops.org", "external_url": "https://dev.yoops.org"},
            "auth": {
                "oidc": {
                    "issuer": "https://kc.test",
                    "client_id": "portal",
                    "client_secret": "",
                }
            },
            "hosts": [host.model_dump()],
        }
    )


@pytest.fixture
def enregistre(monkeypatch: pytest.MonkeyPatch) -> list[GlobalConfig]:
    """Capture ce qui part en base, sans base."""
    vues: list[GlobalConfig] = []

    async def _save(cfg: GlobalConfig, conn: Any) -> None:
        vues.append(cfg)

    async def _sync(name: str) -> None:
        return None

    monkeypatch.setattr(admin, "save_global_db", _save)
    monkeypatch.setattr(admin, "set_cached_global", lambda cfg: None)
    monkeypatch.setattr(admin.bastion_servers, "sync_server_host", _sync)
    return vues


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, enregistre: list[GlobalConfig]) -> TestClient:
    host = HostConfig(
        name="worker01",
        type="docker-tls",
        docker_host="tcp://10.0.0.5:2376",
        profile_slug="gros-noeud",
        hypervisor="pve-1",
        capacity_workspaces=10,
    )
    monkeypatch.setattr(admin, "load_global", lambda: _config(host))

    app = FastAPI()
    # Le handler lit `request.session` (id de session pour la matérialisation
    # des certificats) : sans le middleware, Starlette casse avant le test.
    app.add_middleware(SessionMiddleware, secret_key="tests-only-not-a-secret")
    app.include_router(admin.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def _corps(**extra: Any) -> dict[str, Any]:
    return {
        "name": "worker01",
        "type": "docker-tls",
        "docker_host": "tcp://10.0.0.5:2376",
        **extra,
    }


def test_capacite_et_ouverture_au_mutualise_sont_enregistrees(
    client: TestClient, enregistre: list[GlobalConfig]
) -> None:
    resp = client.put(
        "/admin/hosts/worker01", json=_corps(capacity_workspaces=8, accepts_mutualise=True)
    )

    assert resp.status_code == 200
    assert resp.json()["capacity_workspaces"] == 8
    assert resp.json()["accepts_mutualise"] is True
    assert enregistre[-1].hosts[0].capacity_workspaces == 8


def test_profil_d_origine_survit_a_un_update_qui_l_ignore(
    client: TestClient, enregistre: list[GlobalConfig]
) -> None:
    """Le client ne renvoie pas la provenance : ce n'est pas à lui de la fixer.

    Elle est posée au provisionnement et ne doit pas s'effacer parce qu'un
    administrateur a changé une adresse IP.
    """
    resp = client.put("/admin/hosts/worker01", json=_corps(capacity_workspaces=8))

    assert resp.status_code == 200
    assert enregistre[-1].hosts[0].profile_slug == "gros-noeud"


def test_l_hyperviseur_d_origine_survit_a_un_update_qui_l_ignore(
    client: TestClient, enregistre: list[GlobalConfig]
) -> None:
    """Même piège que `profile_slug`, même remède.

    L'hyperviseur qui a monté la machine est une PROVENANCE : posée au
    provisionnement, jamais saisie par l'administrateur. Le handler reconstruit
    un `HostConfig` champ par champ — l'oublier ici l'effacerait à chaque
    changement d'adresse IP, et le comptage des machines par hyperviseur se
    remettrait à mentir sans que rien ne le signale.
    """
    resp = client.put("/admin/hosts/worker01", json=_corps(capacity_workspaces=8))

    assert resp.status_code == 200
    assert enregistre[-1].hosts[0].hypervisor == "pve-1"


def test_capacite_absente_du_corps_est_preservee(
    client: TestClient, enregistre: list[GlobalConfig]
) -> None:
    """Un update partiel n'efface pas une capacité déjà saisie.

    Effacer une capacité, c'est rendre la machine « non renseignée » : le
    décideur cesse alors de savoir combien elle tient, et le pool s'en détourne.
    """
    resp = client.put("/admin/hosts/worker01", json=_corps())

    assert resp.status_code == 200
    assert enregistre[-1].hosts[0].capacity_workspaces == 10


def test_capacite_negative_refusee(client: TestClient) -> None:
    resp = client.put("/admin/hosts/worker01", json=_corps(capacity_workspaces=-1))

    assert resp.status_code == 422
