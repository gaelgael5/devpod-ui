"""La vue « parc » des hôtes, contre le vrai schéma.

Ce que ces tests verrouillent — les deux règles qui ne se voient pas dans une
capture d'écran, et les décisions de la fiche :

- une machine jamais sondée n'arrive JAMAIS en tête d'un tri, dans aucun sens ;
- l'ordre est stable : à valeur égale, le nom départage — aucune machine ne
  disparaît ni n'apparaît deux fois en changeant de page ;
- le filtre propriétaire porte l'entrée « Mutualisé », qui rend exactement les
  machines du pool ; les deux filtres se combinent.
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.db.host_parc import FILTRE_MUTUALISE, lister_parc
from portal.db.tables import host_disk, host_ownership, hosts, users, workspace_status


async def _seed_user(conn, login: str) -> None:
    await conn.execute(
        insert(users).values(
            login=login,
            version="1",
            secret_ns=str(uuid.uuid4()),
            default_ide="openvscode",
            default_idle_timeout="2h",
            harpocrate_api_key="",
        )
    )


async def _host(
    conn,
    nom: str,
    *,
    mutualise: bool = False,
    owner: str | None = None,
    disque: int | None = None,
    memoire: int | None = None,
    workspaces: int = 0,
    usage: str = "workspaces",
) -> None:
    await conn.execute(
        insert(hosts).values(name=nom, type="docker-tls", accepts_mutualise=mutualise, usage=usage)
    )
    if owner is not None:
        await conn.execute(insert(host_ownership).values(host_name=nom, owner_login=owner))
    if disque is not None or memoire is not None:
        await conn.execute(
            insert(host_disk).values(
                name=nom, used_pct=disque, mem_used_bytes=memoire, mem_total_bytes=8_000_000_000
            )
        )
    for i in range(workspaces):
        await conn.execute(
            insert(workspace_status).values(
                ws_id=f"{nom}-ws-{i}", status="running", login="alice", host_name=nom
            )
        )


async def test_les_deux_natures_se_lisent_sur_la_ligne(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _host(db_conn, "mut-1", mutualise=True)
    await _host(db_conn, "ded-1", owner="alice")

    page = await lister_parc(db_conn)

    lignes = {ligne.name: ligne for ligne in page.hosts}
    assert lignes["mut-1"].accepts_mutualise is True
    assert lignes["mut-1"].owner_login is None
    assert lignes["ded-1"].owner_login == "alice"
    assert page.proprietaires == ["alice"]


async def test_le_filtre_mutualise_rend_le_pool_et_lui_seul(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _host(db_conn, "mut-1", mutualise=True)
    await _host(db_conn, "ded-1", owner="alice")

    page = await lister_parc(db_conn, owner=FILTRE_MUTUALISE)

    assert [ligne.name for ligne in page.hosts] == ["mut-1"]


async def test_les_deux_filtres_se_combinent(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _host(db_conn, "mut-alpha", mutualise=True)
    await _host(db_conn, "mut-beta", mutualise=True)

    page = await lister_parc(db_conn, owner=FILTRE_MUTUALISE, q="alpha")

    assert [ligne.name for ligne in page.hosts] == ["mut-alpha"]


async def test_le_decompte_de_workspaces_est_agrege_et_triable(db_conn) -> None:
    await _host(db_conn, "calme", workspaces=1)
    await _host(db_conn, "charge", workspaces=3)
    await _host(db_conn, "vide")

    page = await lister_parc(db_conn, tri="workspaces", descendant=True)

    assert [(ligne.name, ligne.workspaces) for ligne in page.hosts] == [
        ("charge", 3),
        ("calme", 1),
        ("vide", 0),  # zéro RÉEL : pas de workspaces, ce n'est pas un inconnu
    ]


async def test_une_machine_jamais_sondee_n_arrive_jamais_en_tete(db_conn) -> None:
    """Le piège de la fiche : un tri naïf place la non-sondée en tête du
    classement « disque le plus libre » — c'est-à-dire recommande d'y poser des
    workspaces alors qu'on ne sait RIEN d'elle."""
    await _host(db_conn, "pleine", disque=90)
    await _host(db_conn, "libre", disque=10)
    await _host(db_conn, "inconnue")  # jamais sondée : pas de ligne host_disk

    montant = await lister_parc(db_conn, tri="disque", descendant=False)
    descendant = await lister_parc(db_conn, tri="disque", descendant=True)

    assert [ligne.name for ligne in montant.hosts] == ["libre", "pleine", "inconnue"]
    assert [ligne.name for ligne in descendant.hosts] == ["pleine", "libre", "inconnue"]
    assert montant.hosts[-1].disk_used_pct is None  # inconnu, pas 0 %


async def test_l_ordre_est_stable_a_valeur_egale(db_conn) -> None:
    """Jeu à valeurs égales, pagination page par page : aucune machine ne
    disparaît ni n'apparaît deux fois — la DoD le demande explicitement."""
    for nom in ("echo", "alpha", "delta", "bravo", "charlie"):
        await _host(db_conn, nom, disque=50)

    vues: list[str] = []
    for page_num in (1, 2, 3):
        page = await lister_parc(db_conn, tri="disque", page=page_num, page_size=2)
        vues.extend(ligne.name for ligne in page.hosts)

    assert vues == ["alpha", "bravo", "charlie", "delta", "echo"]
    assert len(set(vues)) == 5


async def test_le_total_suit_les_filtres(db_conn) -> None:
    await _host(db_conn, "mut-1", mutualise=True)
    await _host(db_conn, "mut-2", mutualise=True)
    await _host(db_conn, "solo")

    page = await lister_parc(db_conn, owner=FILTRE_MUTUALISE, page_size=1)

    assert page.total == 2
    assert len(page.hosts) == 1


async def test_les_usages_exclus_sortent_de_la_vue(db_conn) -> None:
    await _host(db_conn, "ws-1")
    await _host(db_conn, "test-1", usage="tests")
    await _host(db_conn, "res-1", usage="ressources")

    page = await lister_parc(db_conn, hors_usages=["tests", "ressources", "autres"])

    assert [ligne.name for ligne in page.hosts] == ["ws-1"]


async def test_le_tri_memoire_suit_les_memes_regles(db_conn) -> None:
    await _host(db_conn, "gourmande", memoire=6_000_000_000)
    await _host(db_conn, "sobre", memoire=1_000_000_000)
    await _host(db_conn, "inconnue")

    page = await lister_parc(db_conn, tri="memoire", descendant=True)

    assert [ligne.name for ligne in page.hosts] == ["gourmande", "sobre", "inconnue"]
