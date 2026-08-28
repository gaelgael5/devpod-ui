"""Le registre des provisionings, contre le vrai schéma.

Ce qui se joue ici : rendre visible l'écart entre « payé » et « accessible ».
Un provisioning qui échoue sans laisser de ligne, c'est un client qui paie pour
rien et personne pour le savoir.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.billing.provisioning import Decision
from portal.db.provisioning_runs import enregistrer, lire, lister_echecs, marquer
from portal.db.tables import offers, subscriptions, users

DECISION_DEDIEE = Decision(
    action="creer_vm_dediee", noeud="pve", motif="forfait dédié : création d'une VM sur pve"
)


async def _seed(conn, *, login: str = "alice", offre: str = "standard") -> str:
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
    await conn.execute(insert(offers).values(slug=offre, hosting_type="dedie"))
    sub_id = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions).values(
            id=sub_id,
            login=login,
            offer_slug=offre,
            state="essai",
            country_code="FR",
            currency="EUR",
            amount_minor=1200,
        )
    )
    return sub_id


async def test_enregistre_le_verdict_tel_quel(db_conn) -> None:
    """Le motif est recopié : on doit pouvoir relire ce qui a été décidé même
    si la règle a changé depuis."""
    sub = await _seed(db_conn)

    run_id = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )

    assert run_id is not None
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["action"] == "creer_vm_dediee"
    assert ligne["state"] == "decide"
    assert "pve" in ligne["motif"]


async def test_un_evenement_rejoue_ne_cree_pas_deux_tentatives(db_conn) -> None:
    """Un webhook rejoué est la norme, pas l'exception."""
    sub = await _seed(db_conn)
    premier = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="activation",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )

    second = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="activation",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )

    assert premier is not None
    assert second is None


async def test_deux_evenements_distincts_font_deux_lignes(db_conn) -> None:
    """L'essai puis l'activation : deux tentatives tracées, même si la seconde
    conclura qu'il n'y a rien à faire."""
    sub = await _seed(db_conn)
    a = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_essai",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )
    b = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_paiement",
        kind="activation",
        owner_login="alice",
        offer_slug="standard",
        decision=Decision(action="rien", motif="l'abonnement a déjà sa machine"),
    )

    assert a != b


async def test_le_cycle_va_de_decide_a_fait(db_conn) -> None:
    sub = await _seed(db_conn)
    run_id = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )
    assert run_id is not None

    await marquer(run_id, "en_cours", db_conn)
    await marquer(run_id, "fait", db_conn)

    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["state"] == "fait"
    assert ligne["erreur"] == ""


async def test_un_echec_porte_son_message_et_se_liste(db_conn) -> None:
    """C'est la raison d'être de la table : l'échec doit se lister, pas défiler
    dans un journal."""
    sub = await _seed(db_conn)
    run_id = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="activation",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )
    assert run_id is not None

    await marquer(run_id, "echec", db_conn, erreur="qm clone a rendu 1 : storage plein")

    echecs = await lister_echecs(db_conn)
    assert [e["id"] for e in echecs] == [run_id]
    assert "storage plein" in echecs[0]["erreur"]


async def test_seuls_les_echecs_sont_listes(db_conn) -> None:
    sub = await _seed(db_conn)
    fait = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_ok",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )
    assert fait is not None
    await marquer(fait, "fait", db_conn)

    assert await lister_echecs(db_conn) == []


async def test_une_reprise_effacee_l_erreur_precedente(db_conn) -> None:
    """Rejouer un provisioning après correction ne doit pas laisser croire
    qu'il échoue encore."""
    sub = await _seed(db_conn)
    run_id = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        kind="activation",
        owner_login="alice",
        offer_slug="standard",
        decision=DECISION_DEDIEE,
    )
    assert run_id is not None
    await marquer(run_id, "echec", db_conn, erreur="storage plein")

    await marquer(run_id, "fait", db_conn)

    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["erreur"] == ""
