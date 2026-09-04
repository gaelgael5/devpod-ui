"""Enforcement des quotas d'un forfait à la création d'un workspace.

Un quota affiché mais jamais appliqué est une promesse creuse. Ces tests
vérifient le branchement DB → règles (`ownership.verifier_creation`,
`allocation.verifier_creation_pool`), contre le vrai schéma :

- le comptage est le RÉEL de la table `workspaces`, résolu à chaque appel ;
- sur une machine dédiée partagée, les workspaces des invités comptent dans le
  plafond de l'owner ;
- `null` = illimité, pour les deux quotas ;
- une machine hors du modèle de facturation reste libre — c'est la décision
  « compte sans abonnement » : libre hors du modèle, refusé dessus ;
- deux créations simultanées à une place du plafond n'en font pas passer deux.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import insert

from portal.billing.allocation import QuotaDepasse
from portal.db.subscription_hosts import rattacher
from portal.db.tables import (
    countries,
    host_guests,
    host_ownership,
    hosts,
    offers,
    users,
    workspaces,
)
from portal.db.tables import subscriptions as subscriptions_t
from portal.db.workspace_quota import verifier_quota_creation, verrouiller_creation


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
    conn, *, nom: str, mutualise: bool = False, capacite: int | None = 4
) -> None:
    await conn.execute(
        insert(hosts).values(
            name=nom,
            type="docker-tls",
            accepts_mutualise=mutualise,
            capacity_workspaces=capacite,
        )
    )


async def _seed_propriete(
    conn, *, nom: str, owner: str, quota_offre: int | None = None
) -> None:
    await conn.execute(
        insert(host_ownership).values(
            host_name=nom,
            owner_login=owner,
            hosting_type="dedie",
            offer_slug="standard",
            offer_max_workspaces=quota_offre,
        )
    )


async def _seed_invite(conn, *, nom: str, login: str, alloue: int | None = None) -> None:
    await conn.execute(
        insert(host_guests).values(
            host_name=nom,
            email=f"{login}@example.invalid",
            login=login,
            allocated_workspaces=alloue,
            state="accepte",
            token=str(uuid.uuid4()),
        )
    )


async def _seed_offre(conn, slug: str = "standard") -> None:
    await conn.execute(insert(countries).values(code="FR", label="France"))
    await conn.execute(insert(offers).values(slug=slug, label=slug))


async def _seed_abonnement(
    conn, *, login: str, offre: str = "standard", etat: str = "actif"
) -> str:
    sid = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions_t).values(
            id=sid,
            login=login,
            offer_slug=offre,
            state=etat,
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


# ─── Hors du modèle de facturation ───────────────────────────────────────────


async def test_une_machine_hors_modele_reste_libre(db_conn) -> None:
    """Ni dédiée ni pool : aucun forfait ne la gouverne. Un compte sans
    abonnement y crée librement — les contrôles d'accès existants s'appliquent,
    pas le quota."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="brut-01", mutualise=False, capacite=None)

    await verifier_quota_creation("alice", "brut-01", db_conn)


async def test_un_workspace_sans_host_cible_passe(db_conn) -> None:
    await _seed_user(db_conn, "alice")

    await verifier_quota_creation("alice", "", db_conn)


async def test_une_machine_inconnue_du_parc_ne_bloque_pas(db_conn) -> None:
    """La validation du host cible appartient au lifecycle, pas au quota."""
    await _seed_user(db_conn, "alice")

    await verifier_quota_creation("alice", "fantome", db_conn)


# ─── Machine dédiée ──────────────────────────────────────────────────────────


async def test_dedie_sous_le_plafond_l_owner_cree(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="vm-alice", capacite=2)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice")
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="vm-alice")

    await verifier_quota_creation("alice", "vm-alice", db_conn)


async def test_dedie_capacite_atteinte_le_refus_nomme_la_machine(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="vm-alice", capacite=1)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice")
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="vm-alice")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("alice", "vm-alice", db_conn)
    assert "capacité" in str(err.value)
    assert "vm-alice" in str(err.value)


async def test_dedie_quota_du_forfait_atteint_le_refus_le_nomme(db_conn) -> None:
    """Capacité machine large, quota commercial plus bas : c'est le forfait qui
    est nommé — l'utilisateur doit savoir qu'un forfait supérieur répond."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="vm-alice", capacite=10)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice", quota_offre=1)
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="vm-alice")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("alice", "vm-alice", db_conn)
    assert "forfait" in str(err.value)


async def test_dedie_les_workspaces_des_invites_comptent_dans_le_plafond(db_conn) -> None:
    """DoD : sur un host partagé, la capacité est COMMUNE — owner et invités
    confondus. Deux workspaces d'invité remplissent une machine de deux."""
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await _seed_host(db_conn, nom="vm-alice", capacite=2)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice")
    await _seed_invite(db_conn, nom="vm-alice", login="bob")
    await _seed_workspace(db_conn, login="bob", nom="b1", host="vm-alice")
    await _seed_workspace(db_conn, login="bob", nom="b2", host="vm-alice")

    with pytest.raises(QuotaDepasse):
        await verifier_quota_creation("alice", "vm-alice", db_conn)


async def test_dedie_un_invite_a_sa_sous_limite(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await _seed_host(db_conn, nom="vm-alice", capacite=10)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice")
    await _seed_invite(db_conn, nom="vm-alice", login="bob", alloue=1)
    await _seed_workspace(db_conn, login="bob", nom="b1", host="vm-alice")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("bob", "vm-alice", db_conn)
    assert "bob" in str(err.value)


async def test_dedie_un_etranger_est_refuse(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "mallory")
    await _seed_host(db_conn, nom="vm-alice", capacite=10)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("mallory", "vm-alice", db_conn)
    assert "invité" in str(err.value)


async def test_dedie_null_partout_vaut_illimite(db_conn) -> None:
    """DoD : `null` = illimité, pour la capacité ET le quota d'offre."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="vm-alice", capacite=None)
    await _seed_propriete(db_conn, nom="vm-alice", owner="alice", quota_offre=None)
    for i in range(20):
        await _seed_workspace(db_conn, login="alice", nom=f"ws{i}", host="vm-alice")

    await verifier_quota_creation("alice", "vm-alice", db_conn)


# ─── Machine du pool mutualisé ───────────────────────────────────────────────


async def test_pool_sous_sa_part_l_abonne_cree(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=8)
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 2, db_conn)
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="mut-01")

    await verifier_quota_creation("alice", "mut-01", db_conn)


async def test_pool_part_epuisee_le_refus_nomme_le_forfait(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=8)
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 1, db_conn)
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="mut-01")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("alice", "mut-01", db_conn)
    assert "forfait" in str(err.value)
    assert "1/1" in str(err.value)


async def test_pool_sans_abonnement_le_refus_dit_quoi_faire(db_conn) -> None:
    """La décision « compte sans abonnement » : sur une machine du modèle, le
    refus est explicite et actionnable — pas un comportement découvert en prod."""
    await _seed_user(db_conn, "alice")
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=8)

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("alice", "mut-01", db_conn)
    assert "abonnement" in str(err.value)


async def test_pool_un_abonnement_resilie_ne_donne_plus_de_place(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=8)
    sid = await _seed_abonnement(db_conn, login="alice", etat="resilie")
    await rattacher(sid, "mut-01", 3, db_conn)

    with pytest.raises(QuotaDepasse):
        await verifier_quota_creation("alice", "mut-01", db_conn)


async def test_pool_les_parts_de_deux_abonnements_s_additionnent(db_conn) -> None:
    """Deux souscriptions à la même offre : deux parts, un seul droit cumulé."""
    await _seed_user(db_conn, "alice")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=8)
    premier = await _seed_abonnement(db_conn, login="alice")
    second = await _seed_abonnement(db_conn, login="alice")
    await rattacher(premier, "mut-01", 1, db_conn)
    await rattacher(second, "mut-01", 1, db_conn)
    await _seed_workspace(db_conn, login="alice", nom="ws1", host="mut-01")

    await verifier_quota_creation("alice", "mut-01", db_conn)


async def test_pool_machine_pleine_meme_avec_une_part_libre(db_conn) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await _seed_offre(db_conn)
    await _seed_host(db_conn, nom="mut-01", mutualise=True, capacite=2)
    sid = await _seed_abonnement(db_conn, login="alice")
    await rattacher(sid, "mut-01", 2, db_conn)
    await _seed_workspace(db_conn, login="bob", nom="b1", host="mut-01")
    await _seed_workspace(db_conn, login="bob", nom="b2", host="mut-01")

    with pytest.raises(QuotaDepasse) as err:
        await verifier_quota_creation("alice", "mut-01", db_conn)
    assert "capacité" in str(err.value)


# ─── Concurrence ─────────────────────────────────────────────────────────────


async def test_deux_creations_simultanees_a_une_place_n_en_font_pas_passer_deux(
    db_engine, postgres_url
) -> None:
    """DoD : le test de concurrence, pas une revue de code.

    Une place reste sur la machine. Deux transactions vérifient puis écrivent,
    en parallèle. Sans verrou, chacune voit la place libre et les deux passent ;
    avec `verrouiller_creation`, la seconde attend le commit de la première et
    compte SA ligne. Exactement un refus attendu.

    Le décor est COMMITÉ (les transactions concurrentes lisent en READ
    COMMITTED), et les deux rivales passent par un moteur à DEUX connexions —
    celui des fixtures n'en a qu'une, la seconde attendrait la première et le
    test ne testerait plus rien.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    async with db_engine.begin() as conn:
        await _seed_user(conn, "alice")
        await _seed_user(conn, "bob")
        await _seed_host(conn, nom="vm-alice", capacite=1)
        await _seed_propriete(conn, nom="vm-alice", owner="alice")
        await _seed_invite(conn, nom="vm-alice", login="bob")

    rivales = create_async_engine(postgres_url, pool_size=2, max_overflow=0)
    try:

        async def _creer(login: str, nom: str) -> str:
            async with rivales.begin() as conn:
                await verrouiller_creation("vm-alice", conn)
                try:
                    await verifier_quota_creation(login, "vm-alice", conn)
                except QuotaDepasse:
                    return "refuse"
                await _seed_workspace(conn, login=login, nom=nom, host="vm-alice")
                return "cree"

        verdicts = await asyncio.gather(_creer("alice", "wa"), _creer("bob", "wb"))
    finally:
        await rivales.dispose()

    assert sorted(verdicts) == ["cree", "refuse"]
