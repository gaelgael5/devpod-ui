"""Taxonomie des échecs contre le vrai schéma (ticket 6).

Ce qui se joue : la distinction n'est pas succès/échec mais ce qu'il reste
derrière. `echec_apres_creation` doit porter son `provider_ref` (sinon la
machine est orpheline), `indetermine` ne se rejoue jamais tout seul, et une
coupure brutale du runner laisse une ligne actionnable — jamais rien.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from portal.billing.orchestration import (
    HostProvisionne,
    RejeuRefuse,
    detruire_reste,
    rejouer,
)
from portal.billing.provisioning import Decision
from portal.db.provisioning_runs import (
    enregistrer,
    lire,
    lister_echecs,
    marquer,
    peut_rejouer,
    requalifier_orphelins,
)
from portal.db.tables import offers, subscriptions, users
from portal.provisioning.driver import register_driver
from portal.provisioning.errors import EchecApresCreation, Indetermine


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


async def _run_assigner(conn, sub: str, *, state: str) -> int:
    """Une tentative `assigner_host` amenée dans l'état voulu."""
    run_id = await enregistrer(
        conn,
        subscription_id=sub,
        provider_event_id=f"evt-{state}",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=Decision(action="assigner_host", host_name="h1", motif="test"),
    )
    assert run_id is not None
    await marquer(run_id, state, conn)  # type: ignore[arg-type]
    return run_id


class _Executeur:
    """Assigne toujours h1 ; peut lever une exception donnée."""

    def __init__(self, leve: BaseException | None = None) -> None:
        self.leve = leve
        self.appels: list[str] = []

    async def creer_vm_dediee(self, **kwargs) -> HostProvisionne:
        raise AssertionError("inattendu")

    async def creer_host_mutualise(self, **kwargs) -> HostProvisionne:
        raise AssertionError("inattendu")

    async def assigner_host(self, *, host_name: str, **kwargs) -> HostProvisionne:
        self.appels.append(host_name)
        if self.leve is not None:
            raise self.leve
        return HostProvisionne(host_name=host_name)


async def test_echec_apres_creation_porte_son_provider_ref(db_conn) -> None:
    """DoD : un échec injecté après la création laisse une trace
    `echec_apres_creation` portant provider_ref — c'est ce qui évite la
    machine orpheline."""
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="echec_avant_creation")
    exc = EchecApresCreation(
        "config incomplète",
        provider_ref={"vmid": "150", "node": "pve"},
        provider="proxmox",
    )

    res = await rejouer(run_id, db_conn, _Executeur(leve=exc))

    assert res.state == "echec_apres_creation"
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["state"] == "echec_apres_creation"
    assert ligne["provider_ref"] == {"vmid": "150", "node": "pve"}
    assert ligne["provider"] == "proxmox"


async def test_coupure_brutale_laisse_une_ligne_actionnable(db_conn) -> None:
    """DoD : aucun chemin ne laisse une machine existante sans ligne. La ligne
    est posée avant l'exécution ; si le runner meurt, elle reste `en_cours` et
    la requalification du boot la rend `indetermine` — visible, jamais rejouée
    seule."""
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="en_cours")

    requalifies = await requalifier_orphelins(db_conn)

    assert requalifies == 1
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["state"] == "indetermine"
    assert "issue inconnue" in ligne["erreur"]


async def test_indetermine_ne_se_rejoue_pas(db_conn) -> None:
    """DoD : un rejeu d'une opération indéterminée est refusé — rejouer un
    apply à l'issue inconnue est la façon de facturer deux VM."""
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="indetermine")

    executeur = _Executeur()
    with pytest.raises(RejeuRefuse):
        await rejouer(run_id, db_conn, executeur)
    assert executeur.appels == []
    assert not peut_rejouer("indetermine")
    assert not peut_rejouer("echec_apres_creation")


async def test_echec_avant_creation_se_rejoue_a_l_identique(db_conn) -> None:
    """DoD : un échec avant création se rejoue sans effet de bord — le verdict
    enregistré est rejoué tel quel, pas re-décidé."""
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="echec_avant_creation")

    executeur = _Executeur()
    res = await rejouer(run_id, db_conn, executeur)

    assert res.state == "fait"
    assert executeur.appels == ["h1"]
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["state"] == "fait"
    assert ligne["erreur"] == ""


async def test_detruire_le_reste_rend_la_tentative_rejouable(db_conn) -> None:
    """DoD : après un echec_apres_creation, « détruire » passe par le driver du
    provider avec le provider_ref tel quel, et la tentative redevient
    rejouable à l'identique."""
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="en_cours")
    await marquer(
        run_id,
        "echec_apres_creation",
        db_conn,
        erreur="config incomplète",
        provider="fake-destroy",
        provider_ref={"vmid": "150", "node": "pve", "exotique": True},
    )

    detruits: list[dict[str, object]] = []

    class _Driver:
        async def provision(self, spec):
            raise AssertionError("inattendu")

        async def destroy(self, provider_ref) -> None:
            detruits.append(provider_ref)

    register_driver("fake-destroy", _Driver())

    res = await detruire_reste(run_id, db_conn)

    assert detruits == [{"vmid": "150", "node": "pve", "exotique": True}]
    assert res.state == "echec_avant_creation"
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert peut_rejouer(str(ligne["state"]))


async def test_les_nouveaux_etats_sont_listes_comme_echecs(db_conn) -> None:
    sub = await _seed(db_conn)
    r1 = await _run_assigner(db_conn, sub, state="echec_avant_creation")
    run_id = await enregistrer(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt-2",
        kind="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        decision=Decision(action="assigner_host", host_name="h2", motif="test"),
    )
    assert run_id is not None
    await marquer(run_id, "indetermine", db_conn)

    echecs = await lister_echecs(db_conn)
    assert {e["id"] for e in echecs} == {r1, run_id}


async def test_timeout_pendant_l_execution_est_indetermine(db_conn) -> None:
    sub = await _seed(db_conn)
    run_id = await _run_assigner(db_conn, sub, state="echec_avant_creation")

    res = await rejouer(run_id, db_conn, _Executeur(leve=Indetermine("délai dépassé")))

    assert res.state == "indetermine"
    ligne = await lire(run_id, db_conn)
    assert ligne is not None
    assert ligne["state"] == "indetermine"
