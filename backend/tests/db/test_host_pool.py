"""L'état du parc mutualisé, lu contre le vrai schéma.

Ce que ces tests protègent : le chiffre de places restantes qui sera donné au
décideur de provisioning. S'il est faux, on assigne un client à une machine
pleine — ou on ouvre une VM de plus pour rien.

Deux invariants ont changé de fondation depuis la première écriture, et ce sont
eux qui structurent ce fichier :

- **le pool se lit sur la MACHINE** (`hosts.accepts_mutualise`), pas sur la
  propriété. Une machine mutualisée n'a pas de propriétaire — la migration 117
  l'écrit noir sur blanc ;
- **l'idempotence se clé sur l'ABONNEMENT**, pas sur le couple (compte, offre).
  L'ancienne clé confondait deux souscriptions légitimes à la même offre, et la
  seconde ne recevait rien, en silence.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.db.host_pool import a_deja_une_machine, pool_mutualise
from portal.db.subscription_hosts import rattacher
from portal.db.tables import countries, hosts, offers, subscriptions, users, workspaces


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
    mutualise: bool = True,
    capacite: int | None = 4,
) -> None:
    """Une machine, et son ouverture au pool.

    Plus aucune ligne de propriété : le pool ne la lit plus, et une machine
    mutualisée n'en a pas.
    """
    await conn.execute(
        insert(hosts).values(
            name=nom,
            type="docker-tls",
            accepts_mutualise=mutualise,
            capacity_workspaces=capacite,
        )
    )


async def _seed_offre(conn, slug: str = "standard") -> None:
    # `subscriptions.country_code` reference `countries.code` : le pays doit
    # exister avant l'abonnement.
    await conn.execute(insert(countries).values(code="FR", label="France"))
    await conn.execute(insert(offers).values(slug=slug, label=slug))


async def _seed_abonnement(conn, *, login: str, offre: str = "standard") -> str:
    """Rend l'identifiant : c'est LUI la clé d'idempotence désormais."""
    sid = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions).values(
            id=sid,
            login=login,
            offer_slug=offre,
            state="actif",
            country_code="FR",
            currency="EUR",
            amount_minor=0,
        )
    )
    return sid


async def _seed_workspace(conn, *, login: str, nom: str, host: str) -> None:
    await conn.execute(
        insert(workspaces).values(
            login=login, name=nom, host=host, source="https://example.invalid/repo.git"
        )
    )


def _places(pool, nom: str) -> int | None:
    return next(h.places_restantes for h in pool if h.host_name == nom)


# ─── Ce qui entre dans le pool ───────────────────────────────────────────────


async def test_pool_vide_quand_aucune_machine_n_est_ouverte(db_conn) -> None:
    await _seed_host(db_conn, nom="prive-01", mutualise=False)

    assert await pool_mutualise(db_conn) == []


async def test_seul_accepts_mutualise_fait_entrer_dans_le_pool(db_conn) -> None:
    """C'est le drapeau de la MACHINE qui décide, et rien d'autre.

    Ouvrir un nœud aux workspaces d'autrui est un acte délibéré de l'exploitant,
    jamais un effet de bord — d'où le défaut à faux (migration 117).
    """
    await _seed_host(db_conn, nom="ouverte", mutualise=True)
    await _seed_host(db_conn, nom="fermee", mutualise=False)

    pool = await pool_mutualise(db_conn)

    assert [h.host_name for h in pool] == ["ouverte"]


async def test_le_pool_est_trie_par_nom(db_conn) -> None:
    """Ordre stable : le décideur tranche déjà les égalités par nom, mais un
    listing instable rendrait les journaux illisibles."""
    await _seed_host(db_conn, nom="mut-b")
    await _seed_host(db_conn, nom="mut-a")

    pool = await pool_mutualise(db_conn)

    assert [h.host_name for h in pool] == ["mut-a", "mut-b"]


# ─── Le calcul des places ────────────────────────────────────────────────────


async def test_machine_neuve_offre_toute_sa_capacite(db_conn) -> None:
    await _seed_host(db_conn, nom="mut-01", capacite=4)

    pool = await pool_mutualise(db_conn)

    assert [(h.host_name, h.places_restantes) for h in pool] == [("mut-01", 4)]


async def test_une_place_vendue_n_est_plus_disponible(db_conn) -> None:
    """Le cœur du modèle : c'est l'ENGAGEMENT qui consomme, pas l'usage.

    Une place vendue et pas encore utilisée reste indisponible. Compter les
    workspaces réellement posés à la place reviendrait à revendre la même place
    à deux abonnés.
    """
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", capacite=4)
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 3, db_conn)

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 1


async def test_les_workspaces_hors_abonnement_consomment_aussi(db_conn) -> None:
    """Une machine enrôlée à la main porte des workspaces qu'aucune part ne
    couvre. Les ignorer surestimerait la place et ferait planter la machine."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", capacite=4)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")
    await _seed_workspace(db_conn, login="alice", nom="ws-2", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 2


async def test_l_engagement_prime_sur_l_usage_quand_il_est_plus_grand(db_conn) -> None:
    """Trois places vendues, une seule utilisée : il reste une place, pas trois.

    Additionner les deux serait aussi faux : le workspace posé occupe une place
    DÉJÀ vendue. On retient le plus grand des deux, pas leur somme.
    """
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", capacite=4)
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 3, db_conn)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 1


async def test_les_workspaces_d_une_autre_machine_ne_comptent_pas(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", capacite=4)
    await _seed_host(db_conn, nom="mut-02", capacite=4)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 3
    assert _places(pool, "mut-02") == 4


async def test_capacite_non_declaree_remonte_none(db_conn) -> None:
    """Trou de configuration, pas machine infinie : le décideur doit pouvoir
    faire la différence."""
    await _seed_host(db_conn, nom="mut-01", capacite=None)

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") is None


async def test_machine_pleine_remonte_zero_et_non_un_negatif(db_conn) -> None:
    """Une machine sur-souscrite après réduction de capacité rendrait un négatif,
    que le décideur lirait comme « de la place »."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", capacite=1)
    await _seed_workspace(db_conn, login="alice", nom="ws-1", host="mut-01")
    await _seed_workspace(db_conn, login="alice", nom="ws-2", host="mut-01")

    pool = await pool_mutualise(db_conn)

    assert _places(pool, "mut-01") == 0


# ─── Idempotence : la clé est l'ABONNEMENT ───────────────────────────────────


async def test_un_abonnement_neuf_n_a_pas_de_machine(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    sid = await _seed_abonnement(db_conn, login="alice")

    assert await a_deja_une_machine(sid, db_conn) is False


async def test_l_activation_qui_suit_un_essai_ne_recree_rien(db_conn) -> None:
    """Le garde-fou : `debut_essai` puis `activation`, même abonnement."""
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01")
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 2, db_conn)

    assert await a_deja_une_machine(sid, db_conn) is True


async def test_deux_souscriptions_a_la_meme_offre_sont_independantes(db_conn) -> None:
    """LE test de non-régression de ce ticket.

    Rien ne justifie d'empêcher quelqu'un de prendre deux fois le même forfait.
    L'ancienne clé (compte, offre) considérait la seconde souscription comme
    déjà provisionnée : elle ne recevait rien, sans le moindre message.

    Limiter l'offre de bienvenue à une par compte est une règle d'ÉLIGIBILITÉ,
    évaluée à la souscription — pas une exception à glisser ici.
    """
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01")
    premier = await _seed_abonnement(db_conn, login="alice", offre="standard")
    second = await _seed_abonnement(db_conn, login="alice", offre="standard")
    await rattacher(premier, "mut-01", 2, db_conn)

    assert await a_deja_une_machine(premier, db_conn) is True
    assert await a_deja_une_machine(second, db_conn) is False


async def test_l_abonnement_d_un_autre_compte_ne_compte_pas(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01")
    celui_de_bob = await _seed_abonnement(db_conn, login="bob")
    celui_d_alice = await _seed_abonnement(db_conn, login="alice")
    await rattacher(celui_de_bob, "mut-01", 1, db_conn)

    assert await a_deja_une_machine(celui_d_alice, db_conn) is False
