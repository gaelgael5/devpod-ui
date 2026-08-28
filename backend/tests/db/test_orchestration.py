"""L'enchaînement du provisioning, contre le vrai schéma.

L'exécuteur est faux — on ne crée pas de VM dans un test — mais tout le reste
est réel : le décideur, le registre, la lecture du parc. Ce qui est vérifié ici,
c'est la SÉQUENCE et ce qu'elle laisse derrière elle, en particulier quand ça
échoue.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.billing.orchestration import HostProvisionne, traiter
from portal.db.provisioning_runs import lire, lister_echecs
from portal.db.tables import host_ownership, hosts, offers, subscriptions, users


class ExecuteurFactice:
    """Note ce qu'on lui demande, et rend une machine."""

    def __init__(self, *, casse: bool = False) -> None:
        self.appels: list[tuple[str, str]] = []
        self.casse = casse

    async def creer_vm_dediee(self, *, owner_login, offer_slug, noeud) -> HostProvisionne:
        self.appels.append(("creer_vm_dediee", noeud))
        if self.casse:
            raise RuntimeError("qm clone a rendu 1 : storage plein")
        return HostProvisionne(host_name=f"vm-{owner_login}", capacity_workspaces=4)

    async def creer_host_mutualise(self, *, owner_login, offer_slug) -> HostProvisionne:
        self.appels.append(("creer_host_mutualise", offer_slug))
        if self.casse:
            raise RuntimeError("pool injoignable")
        return HostProvisionne(host_name="mut-neuf", capacity_workspaces=8)

    async def assigner_host(self, *, owner_login, offer_slug, host_name) -> HostProvisionne:
        self.appels.append(("assigner_host", host_name))
        if self.casse:
            raise RuntimeError("host injoignable")
        return HostProvisionne(host_name=host_name)


async def _seed(conn, *, login: str = "alice", offre: str = "standard", hebergement: str = "dedie"):
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
    await conn.execute(insert(offers).values(slug=offre, hosting_type=hebergement))
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


async def _seed_host_mutualise(conn, *, nom: str, owner: str, capacite: int | None) -> None:
    await conn.execute(insert(hosts).values(name=nom, type="docker-tls"))
    await conn.execute(
        insert(host_ownership).values(
            host_name=nom,
            owner_login=owner,
            hosting_type="mutualise",
            capacity_workspaces=capacite,
        )
    )


async def test_un_essai_dedie_cree_une_vm_et_trace_le_succes(db_conn) -> None:
    sub = await _seed(db_conn)
    executeur = ExecuteurFactice()

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        executeur=executeur,
    )

    assert res.state == "fait"
    assert executeur.appels == [("creer_vm_dediee", "pve")]
    ligne = await lire(res.run_id or 0, db_conn)
    assert ligne is not None
    assert ligne["state"] == "fait"


async def test_un_echec_est_trace_et_ne_remonte_pas(db_conn) -> None:
    """Le webhook doit répondre au provider : lever ferait rejouer un événement
    qui échouera pareil. L'échec devient une ligne, listable et rejouable."""
    sub = await _seed(db_conn)

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="activation",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        executeur=ExecuteurFactice(casse=True),
    )

    assert res.state == "echec"
    assert "storage plein" in res.erreur
    echecs = await lister_echecs(db_conn)
    assert [e["id"] for e in echecs] == [res.run_id]


async def test_le_rejeu_d_un_evenement_n_execute_rien(db_conn) -> None:
    sub = await _seed(db_conn)
    executeur = ExecuteurFactice()
    commun = {
        "subscription_id": sub,
        "provider_event_id": "evt_1",
        "evenement": "debut_essai",
        "owner_login": "alice",
        "offer_slug": "standard",
        "hosting_type": "dedie",
        "executeur": executeur,
    }

    await traiter(db_conn, **commun)
    second = await traiter(db_conn, **commun)

    assert second.state == "rejeu"
    assert second.run_id is None
    assert len(executeur.appels) == 1


async def test_activation_apres_une_machine_existante_ne_provisionne_pas(db_conn) -> None:
    """Le second garde-fou : la machine existe déjà pour cette offre, l'action
    est « rien » — et la tentative est tout de même tracée."""
    sub = await _seed(db_conn)
    await db_conn.execute(insert(hosts).values(name="vm-alice", type="docker-tls"))
    await db_conn.execute(
        insert(host_ownership).values(
            host_name="vm-alice",
            owner_login="alice",
            hosting_type="dedie",
            offer_slug="standard",
            capacity_workspaces=4,
        )
    )
    executeur = ExecuteurFactice()

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_paiement",
        evenement="activation",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        executeur=executeur,
    )

    assert res.decision.action == "rien"
    assert res.state == "fait"
    assert executeur.appels == []


async def test_mutualise_prend_la_machine_la_plus_remplie(db_conn) -> None:
    sub = await _seed(db_conn, hebergement="mutualise")
    await _seed_host_mutualise(db_conn, nom="mut-01", owner="alice", capacite=7)
    await _seed_host_mutualise(db_conn, nom="mut-02", owner="alice", capacite=2)
    executeur = ExecuteurFactice()

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="mutualise",
        executeur=executeur,
    )

    assert executeur.appels == [("assigner_host", "mut-02")]
    assert res.host_name == "mut-02"


async def test_mutualise_sans_place_ouvre_une_machine(db_conn) -> None:
    sub = await _seed(db_conn, hebergement="mutualise")
    await _seed_host_mutualise(db_conn, nom="mut-01", owner="alice", capacite=0)
    executeur = ExecuteurFactice()

    await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="mutualise",
        executeur=executeur,
    )

    assert executeur.appels == [("creer_host_mutualise", "standard")]


async def test_la_trace_precede_l_execution(db_conn) -> None:
    """Une VM créée sans ligne de suivi est une machine orpheline ; une ligne
    sans VM est un échec visible. On veut la seconde faute, jamais la première."""
    sub = await _seed(db_conn)
    vues: list[str | None] = []

    class ExecuteurQuiRegarde(ExecuteurFactice):
        async def creer_vm_dediee(self, **kwargs) -> HostProvisionne:
            echecs = await lister_echecs(db_conn)
            vues.append("trace_absente" if echecs is None else "trace_presente")
            return await super().creer_vm_dediee(**kwargs)

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        executeur=ExecuteurQuiRegarde(),
    )

    ligne = await lire(res.run_id or 0, db_conn)
    assert ligne is not None
    # La ligne existait déjà pendant l'exécution : elle a été posée avant.
    assert vues == ["trace_presente"]
