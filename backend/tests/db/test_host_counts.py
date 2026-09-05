"""Machines portées par hyperviseur, ventilées par nature et par vivacité.

Ce que l'écran Hyperviseurs consomme. Verrouillé ici :

- le rattachement passe par la PROVENANCE (`hosts.hypervisor`), jamais par un
  rapprochement de noms de nœuds ;
- une machine jamais sondée n'est comptée NI comme active NI comme arrêtée —
  elle a son propre compteur, son cas doit se voir ;
- une machine sans provenance n'est attribuée à personne : elle remonte dans un
  compte à part, affichable tel quel ;
- UNE seule requête agrégée pour toute la page.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

from sqlalchemy import insert

from portal.db.host_counts import machines_par_hyperviseur
from portal.db.tables import host_health, hosts


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


async def test_les_compteurs_se_ventilent_par_nature(db_conn) -> None:
    await _machine(db_conn, "w1", provenance="pve-a", usage="workspaces", joignable=True)
    await _machine(db_conn, "w2", provenance="pve-a", usage="workspaces", joignable=True)
    await _machine(db_conn, "t1", provenance="pve-a", usage="tests", joignable=True)
    await _machine(db_conn, "r1", provenance="pve-a", usage="ressources", joignable=True)

    comptes = await machines_par_hyperviseur(db_conn)

    assert comptes.par_hyperviseur["pve-a"].workspaces == 2
    assert comptes.par_hyperviseur["pve-a"].tests == 1
    assert comptes.par_hyperviseur["pve-a"].ressources == 1


async def test_portail_et_autres_ne_disparaissent_pas_en_silence(db_conn) -> None:
    """La fiche l'exige : `autres` (et `portail`) s'agrègent dans un quatrième
    compteur plutôt que de disparaître — une machine portée reste une machine
    portée, quelle que soit sa destination."""
    await _machine(db_conn, "p1", provenance="pve-a", usage="portail", joignable=True)
    await _machine(db_conn, "a1", provenance="pve-a", usage="autres", joignable=True)

    comptes = await machines_par_hyperviseur(db_conn)

    assert comptes.par_hyperviseur["pve-a"].autres == 2
    assert comptes.par_hyperviseur["pve-a"].workspaces == 0


async def test_jamais_sondee_ni_active_ni_arretee(db_conn) -> None:
    await _machine(db_conn, "active", provenance="pve-a", joignable=True)
    await _machine(db_conn, "arretee", provenance="pve-a", joignable=False)
    await _machine(db_conn, "neuve", provenance="pve-a", joignable=None)

    comptes = await machines_par_hyperviseur(db_conn)

    ligne = comptes.par_hyperviseur["pve-a"]
    assert ligne.workspaces == 1
    assert ligne.jamais_sondees == 1


async def test_sans_provenance_personne_ne_se_l_attribue(db_conn) -> None:
    """Un lien deviné est pire qu'un lien absent : la machine remonte dans un
    compte à part, l'écran la montre comme telle."""
    await _machine(db_conn, "manuelle", provenance="", joignable=True)

    comptes = await machines_par_hyperviseur(db_conn)

    assert comptes.par_hyperviseur == {}
    assert comptes.sans_provenance == 1
