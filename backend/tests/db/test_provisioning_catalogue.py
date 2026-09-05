"""La charge par hyperviseur, telle que l'équilibrage la consomme.

Ce qui est verrouillé ici, dans l'ordre où ça coûte :

- le rattachement machine → hyperviseur passe par la PROVENANCE
  (`hosts.hypervisor`), jamais par un rapprochement de noms de nœuds ;
- une machine jamais sondée compte comme en marche — la traiter comme absente
  enverrait toute la charge vers les machines qui viennent de naître ;
- deux entrées d'hyperviseur visant le même fer partagent leur charge — sinon
  l'une paraît pleine, l'autre vide, et tout part sur la même machine physique.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    Hypervisor,
    OidcConfig,
    ServerConfig,
)
from portal.db.provisioning_catalogue import charger_catalogue
from portal.db.tables import host_health, hosts


def _hyperviseur(nom: str, *, adresse: str = "10.0.0.1", noeud: str = "pve") -> Hypervisor:
    return Hypervisor(
        name=nom,
        address=adresse,
        ssh_key_path="/dev/null",
        pve_node=noeud,
        hypervisor_type="proxmox4vm",
    )


def _config(*hyperviseurs: Hypervisor) -> GlobalConfig:
    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisors=list(hyperviseurs),
    )


@pytest.fixture
def _parc(monkeypatch: pytest.MonkeyPatch):
    def poser(cfg: GlobalConfig) -> None:
        monkeypatch.setattr("portal.db.provisioning_catalogue.load_global", lambda *a, **k: cfg)

    return poser


async def _machine(
    conn,
    nom: str,
    *,
    provenance: str,
    usage: str = "workspaces",
    joignable: bool | None = None,
) -> None:
    await conn.execute(
        insert(hosts).values(name=nom, type="docker-tls", usage=usage, hypervisor=provenance)
    )
    if joignable is not None:
        await conn.execute(insert(host_health).values(name=nom, reachable=joignable))


async def test_la_charge_se_lit_sur_la_provenance_jamais_sur_le_noeud(db_conn, _parc) -> None:
    _parc(_config(_hyperviseur("pve-a"), _hyperviseur("pve-b", adresse="10.0.0.2", noeud="pve2")))
    await _machine(db_conn, "m1", provenance="pve-a")
    await _machine(db_conn, "m2", provenance="pve-a")
    # Provenance vide : machine enrôlée à la main. Même si son `proxmox_node`
    # correspondait, un lien deviné est pire qu'un lien absent — elle ne compte
    # pour personne.
    await _machine(db_conn, "manuelle", provenance="")

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {"pve-a": 2, "pve-b": 0}


async def test_seules_les_machines_a_workspaces_pesent(db_conn, _parc) -> None:
    _parc(_config(_hyperviseur("pve-a")))
    await _machine(db_conn, "ws", provenance="pve-a", usage="workspaces")
    await _machine(db_conn, "vm-test", provenance="pve-a", usage="tests")
    await _machine(db_conn, "ressource", provenance="pve-a", usage="ressources")

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {"pve-a": 1}


async def test_une_machine_injoignable_ne_pese_plus(db_conn, _parc) -> None:
    _parc(_config(_hyperviseur("pve-a")))
    await _machine(db_conn, "vivante", provenance="pve-a", joignable=True)
    await _machine(db_conn, "morte", provenance="pve-a", joignable=False)

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {"pve-a": 1}


async def test_une_machine_jamais_sondee_compte_comme_en_marche(db_conn, _parc) -> None:
    """Sans ligne `host_health`, l'état est inconnu — pas « arrêtée ». La
    compter absente enverrait toute la charge vers les machines qui viennent de
    naître, celles qu'aucune sonde n'a encore vues."""
    _parc(_config(_hyperviseur("pve-a")))
    await _machine(db_conn, "neuve", provenance="pve-a", joignable=None)

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {"pve-a": 1}


async def test_deux_entrees_sur_le_meme_fer_partagent_leur_charge(db_conn, _parc) -> None:
    """Une bascule d'accès SSH déclare deux fois la même machine physique. Ce
    qui sature est le fer : compter par entrée verrait l'ancienne pleine et la
    nouvelle vide, et enverrait tout… sur le même fer."""
    _parc(
        _config(
            _hyperviseur("ancien-acces"),
            _hyperviseur("nouvel-acces"),  # même adresse, même nœud
            _hyperviseur("autre-fer", adresse="10.0.0.9"),
        )
    )
    await _machine(db_conn, "m1", provenance="ancien-acces")
    await _machine(db_conn, "m2", provenance="ancien-acces")

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {
        "ancien-acces": 2,
        "nouvel-acces": 2,
        "autre-fer": 0,
    }


async def test_une_provenance_vers_un_hyperviseur_disparu_ne_pese_sur_personne(
    db_conn, _parc
) -> None:
    _parc(_config(_hyperviseur("pve-a")))
    await _machine(db_conn, "orpheline", provenance="retire-du-parc")

    catalogue = await charger_catalogue(db_conn)

    assert catalogue.charge_par_hyperviseur == {"pve-a": 0}
