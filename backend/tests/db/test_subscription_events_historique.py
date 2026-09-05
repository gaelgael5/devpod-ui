"""L'historique des abonnements : une source, trois points d'accès.

Ce que ces tests verrouillent :

- l'attribution d'une entrée à son compte — par le `login` de l'événement quand
  le canal l'a su, sinon par l'abonnement rattaché ;
- le filtre de visibilité : l'utilisateur voit ses ACHATS, jamais les entrées
  d'exploitation — c'est l'entrée qui porte le filtre, pas trois requêtes ;
- la page globale montre les orphelines (login vide) : c'est là qu'un écart de
  rattachement doit se voir ;
- l'ordre : du plus récent au plus ancien, borné.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert

from portal.db.subscription_events import historique_de, historique_global
from portal.db.tables import countries, offers, subscription_events, subscriptions, users


async def _seed_compte(conn, login: str) -> None:
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


async def _seed_abonnement(conn, *, login: str) -> str:
    sid = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions).values(
            id=sid,
            login=login,
            offer_slug="standard",
            state="actif",
            country_code="FR",
            currency="EUR",
            amount_minor=0,
        )
    )
    return sid


async def _entree(
    conn,
    *,
    kind: str = "activation",
    subscription_id: str | None = None,
    login: str = "",
    visibilite: str = "achat",
    quand: datetime | None = None,
) -> None:
    await conn.execute(
        insert(subscription_events).values(
            kind=kind,
            subscription_id=subscription_id,
            login=login,
            provider_slug="stripe-fr",
            provider_event_id=f"evt_{uuid.uuid4().hex[:10]}",
            visibilite=visibilite,
            occurred_at=quand or datetime.now(UTC),
        )
    )


async def _decor(conn) -> str:
    await _seed_compte(conn, "alice")
    await _seed_compte(conn, "bob")
    await conn.execute(insert(countries).values(code="FR", label="France"))
    await conn.execute(insert(offers).values(slug="standard", label="Standard"))
    return await _seed_abonnement(conn, login="alice")


async def test_l_attribution_passe_par_l_abonnement_ou_par_l_evenement(db_conn) -> None:
    sid = await _decor(db_conn)
    await _entree(db_conn, subscription_id=sid)  # rattachée, login vide
    await _entree(db_conn, login="alice")  # login porté par l'événement
    await _entree(db_conn, login="bob", kind="resiliation")

    entrees = await historique_de("alice", db_conn, achats_seulement=True)

    assert len(entrees) == 2
    assert all(e["login"] == "alice" for e in entrees)


async def test_l_utilisateur_ne_voit_jamais_les_operations(db_conn) -> None:
    sid = await _decor(db_conn)
    await _entree(db_conn, subscription_id=sid, visibilite="achat")
    await _entree(db_conn, subscription_id=sid, kind="debut_essai", visibilite="operation")

    achats = await historique_de("alice", db_conn, achats_seulement=True)
    complet = await historique_de("alice", db_conn, achats_seulement=False)

    assert [e["visibilite"] for e in achats] == ["achat"]
    assert len(complet) == 2


async def test_du_plus_recent_au_plus_ancien(db_conn) -> None:
    sid = await _decor(db_conn)
    await _entree(db_conn, subscription_id=sid, kind="debut_essai")
    await _entree(db_conn, subscription_id=sid, kind="activation")

    entrees = await historique_de("alice", db_conn, achats_seulement=True)

    assert [e["kind"] for e in entrees] == ["activation", "debut_essai"]


async def test_la_page_globale_montre_les_orphelines(db_conn) -> None:
    """Un webhook authentique jamais rattaché ne doit pas disparaître : c'est
    ici qu'un écart de rattachement se cherche."""
    await _decor(db_conn)
    await _entree(db_conn)  # ni abonnement, ni login

    entrees = await historique_global(db_conn)

    assert len(entrees) == 1
    assert entrees[0]["login"] == ""


async def test_la_page_globale_est_bornee(db_conn) -> None:
    sid = await _decor(db_conn)
    for _ in range(5):
        await _entree(db_conn, subscription_id=sid)

    assert len(await historique_global(db_conn, limite=3)) == 3


async def test_le_payload_n_est_jamais_servi(db_conn) -> None:
    """La charge brute du fournisseur est un outil de rejeu, pas une donnée
    d'affichage — et surtout pas une donnée à servir au client."""
    sid = await _decor(db_conn)
    await _entree(db_conn, subscription_id=sid)

    (entree,) = await historique_de("alice", db_conn, achats_seulement=True)

    assert "payload" not in entree
    assert entree["offer_slug"] == "standard"


# ─── Le garde-fou des essais offerts ─────────────────────────────────────────


async def _essai_offert(conn, *, subscription_id: str) -> None:
    await conn.execute(
        insert(subscription_events).values(
            kind="debut_essai",
            subscription_id=subscription_id,
            login="alice",
            provider_slug="portail",
            provider_event_id=f"essai_admin:{subscription_id}",
            occurred_at=datetime.now(UTC),
        )
    )


async def test_un_essai_offert_se_retrouve_par_compte_et_offre(db_conn) -> None:
    from portal.db.subscription_events import essai_deja_offert

    sid = await _decor(db_conn)
    await _essai_offert(db_conn, subscription_id=sid)

    assert await essai_deja_offert("alice", "standard", db_conn) is True
    # Ni un autre compte, ni une autre offre : la clef est le couple.
    assert await essai_deja_offert("bob", "standard", db_conn) is False
    assert await essai_deja_offert("alice", "autre", db_conn) is False


async def test_un_debut_essai_venu_du_canal_de_vente_ne_compte_pas(db_conn) -> None:
    """Seuls les essais OFFERTS par l'admin arment le garde-fou : un essai
    entamé via le canal de vente est un parcours commercial normal."""
    from portal.db.subscription_events import essai_deja_offert

    sid = await _decor(db_conn)
    await _entree(db_conn, subscription_id=sid, kind="debut_essai")

    assert await essai_deja_offert("alice", "standard", db_conn) is False
