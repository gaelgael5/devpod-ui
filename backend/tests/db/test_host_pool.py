"""L'état du parc mutualisé, lu contre le vrai schéma.

Ce que ces tests protègent : le chiffre de places restantes qui sera donné au
décideur de provisioning. S'il est faux, on assigne un client à une machine
pleine — ou on ouvre une VM de plus pour rien.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.db.host_pool import a_deja_une_machine, pool_mutualise
from portal.db.tables import host_ownership, hosts, users, workspaces


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


async def _seed_host(
    conn,
    *,
    nom: str,
    owner: str,
    hosting_type: str = "mutualise",
    capacite: int | None = 4,
    quota: int | None = None,
    offre: str | None = None,
) -> None:
    # `host_ownership.host_name` reference `hosts.name` : la machine doit
    # exister avant qu'on lui donne un proprietaire.
    await conn.execute(insert(hosts).values(name=nom, type="docker-tls"))
    await conn.execute(
        insert(host_ownership).values(
            host_name=nom,
            owner_login=owner,
            hosting_type=hosting_type,
            offer_slug=offre,
            capacity_workspaces=capacite,
            offer_max_workspaces=quota,
        )
    )


async def _seed_workspace(conn, *, login: str, nom: str, host: str) -> None:
    await conn.execute(
        insert(workspaces).values(
            login=login, name=nom, host=host, source="https://example.invalid/repo.git"
        )
    )


async def test_pool_vide_quand_aucun_host_mutualise(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="dedie-01", owner="alice", hosting_type="dedie")

    assert await pool_mutualise(db_conn) == []


async def test_host_neuf_offre_toute_sa_capacite(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=4)

    pool = await pool_mutualise(db_conn)

    assert [(h.host_name, h.places_restantes) for h in pool] == [("mut-01", 4)]


async def test_les_workspaces_poses_consomment_des_places(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=4)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")
    await _seed_workspace(db_conn, login="alice", nom="ws-2", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert pool[0].places_restantes == 2


def _places(pool, nom: str) -> int | None:
    return next(h.places_restantes for h in pool if h.host_name == nom)


async def test_les_workspaces_d_un_autre_host_ne_comptent_pas(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=4)
    await _seed_host(db_conn, nom="mut-02", owner="alice", capacite=4)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 3
    assert _places(pool, "mut-02") == 4


async def test_le_quota_du_forfait_abaisse_la_capacite_machine(db_conn) -> None:
    """Les deux plafonds s'appliquent, le plus bas gagne — c'est la règle
    d'`ownership.limite_effective`, et ce module ne la réécrit pas."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=10, quota=3)

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 3


async def test_capacite_non_declaree_remonte_none(db_conn) -> None:
    """Trou de configuration, pas machine infinie : le décideur doit pouvoir
    faire la différence."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=None)

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") is None


async def test_host_plein_remonte_zero_et_non_un_negatif(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", owner="alice", capacite=1)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")
    await _seed_workspace(db_conn, login="alice", nom="ws-2", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 0


async def test_le_pool_est_trie_par_nom(db_conn) -> None:
    """Ordre stable : le décideur tranche déjà les égalités par nom, mais un
    listing instable rendrait les journaux illisibles."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-b", owner="alice")
    await _seed_host(db_conn, nom="mut-a", owner="alice")

    pool = await pool_mutualise(db_conn)

    assert [h.host_name for h in pool] == ["mut-a", "mut-b"]


# ─── Idempotence du provisioning ─────────────────────────────────────────────


async def test_sans_machine_pour_cette_offre(db_conn) -> None:
    await _seed_user(db_conn, "alice")

    assert await a_deja_une_machine("alice", "standard", db_conn) is False


async def test_une_machine_deja_provisionnee_pour_cette_offre(db_conn) -> None:
    """Le garde-fou de l'activation qui suit un essai : la machine existe déjà."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="dedie-01", owner="alice", hosting_type="dedie", offre="standard")

    assert await a_deja_une_machine("alice", "standard", db_conn) is True


async def test_la_machine_d_une_autre_offre_ne_compte_pas(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="dedie-01", owner="alice", hosting_type="dedie", offre="max")

    assert await a_deja_une_machine("alice", "standard", db_conn) is False


async def test_la_machine_d_un_autre_compte_ne_compte_pas(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await _seed_host(db_conn, nom="dedie-01", owner="bob", hosting_type="dedie", offre="standard")

    assert await a_deja_une_machine("alice", "standard", db_conn) is False
