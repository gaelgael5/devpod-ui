"""L'enchaînement du provisioning, contre le vrai schéma.

L'exécuteur est faux — on ne crée pas de VM dans un test — mais tout le reste
est réel : le décideur, le registre, la lecture du parc. Ce qui est vérifié ici,
c'est la SÉQUENCE et ce qu'elle laisse derrière elle, en particulier quand ça
échoue.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from portal.billing.orchestration import HostProvisionne, traiter
from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    Hypervisor,
    OidcConfig,
    ServerConfig,
)
from portal.db.host_pool import a_deja_une_machine
from portal.db.provisioning_runs import lire, lister_echecs
from portal.db.subscription_hosts import rattacher
from portal.db.tables import (
    host_ownership,
    host_profiles,
    hosts,
    machine_profiles,
    offers,
    subscriptions,
    users,
)

#: Profils de host de l'offre, dans l'ordre de priorité. Un seul suffit ici :
#: le repli sur le suivant est couvert sans base dans tests/billing/test_cible.py.
PROFILS = ["host-standard"]


class ExecuteurFactice:
    """Note ce qu'on lui demande, et rend une machine."""

    def __init__(self, *, casse: bool = False) -> None:
        self.appels: list[tuple[str, str]] = []
        self.casse = casse

    async def creer_vm_dediee(
        self, *, subscription_id, owner_login, offer_slug, noeud, cible
    ) -> HostProvisionne:
        self.appels.append(("creer_vm_dediee", noeud))
        if self.casse:
            raise RuntimeError("qm clone a rendu 1 : storage plein")
        return HostProvisionne(host_name=f"vm-{owner_login}", capacity_workspaces=4)

    async def creer_host_mutualise(
        self, *, subscription_id, owner_login, offer_slug, cible
    ) -> HostProvisionne:
        self.appels.append(("creer_host_mutualise", offer_slug))
        if self.casse:
            raise RuntimeError("pool injoignable")
        return HostProvisionne(host_name="mut-neuf", capacity_workspaces=8)

    async def assigner_host(
        self, *, subscription_id, owner_login, offer_slug, host_name
    ) -> HostProvisionne:
        self.appels.append(("assigner_host", host_name))
        if self.casse:
            raise RuntimeError("host injoignable")
        return HostProvisionne(host_name=host_name)


@pytest.fixture(autouse=True)
def _hyperviseur_declare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un hyperviseur du bon type, sinon aucune cible ne se résout.

    Les hyperviseurs vivent dans la configuration globale et non en base : c'est
    le seul maillon de la chaîne qu'un test DB ne peut pas semer.
    """
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisors=[
            Hypervisor(
                name="pve-a",
                address="10.0.0.1",
                ssh_key_path="/dev/null",
                pve_node="pve",
                hypervisor_type="proxmox4vm",
            )
        ]
    )
    monkeypatch.setattr(
        "portal.db.provisioning_catalogue.load_global", lambda *a, **k: cfg
    )


async def _seed_catalogue(conn) -> None:
    """Les deux maillons stockés en base : profil de machine, profil de host."""
    await conn.execute(
        insert(machine_profiles).values(
            slug="pve-4g", label="4 Go", hypervisor_type="proxmox4vm"
        )
    )
    await conn.execute(
        insert(host_profiles).values(
            slug="host-standard", label="Standard", machine_profile="pve-4g"
        )
    )


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
    await _seed_catalogue(conn)
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
    """Une machine ouverte au pool.

    `owner` n'est plus utilise : une machine mutualisee n'a pas de proprietaire,
    et le pool se lit sur `hosts.accepts_mutualise` (migrations 117 et 125). Le
    parametre reste pour ne pas toucher les appelants.
    """
    await conn.execute(
        insert(hosts).values(
            name=nom,
            type="docker-tls",
            accepts_mutualise=True,
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
        host_profiles=PROFILS,
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
        host_profiles=PROFILS,
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
        "host_profiles": PROFILS,
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
    # La cle d'idempotence est l'ABONNEMENT : c'est son rattachement qui dit
    # qu'il a deja sa machine, pas une ligne de propriete.
    await rattacher(sub, "vm-alice", None, db_conn)
    executeur = ExecuteurFactice()

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_paiement",
        evenement="activation",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        host_profiles=PROFILS,
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
        host_profiles=PROFILS,
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
        host_profiles=PROFILS,
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
        host_profiles=PROFILS,
        executeur=ExecuteurQuiRegarde(),
    )

    ligne = await lire(res.run_id or 0, db_conn)
    assert ligne is not None
    # La ligne existait déjà pendant l'exécution : elle a été posée avant.
    assert vues == ["trace_presente"]


async def test_sans_cible_resoluble_l_echec_est_trace_et_rien_n_est_tente(db_conn) -> None:
    """L'offre ne liste aucun profil de host : il n'y a rien à monter, mais le
    client a payé. Le verdict est un ÉCHEC listable, pas un « rien à faire » —
    sans quoi l'écart entre le paiement et l'accès resterait invisible."""
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
        host_profiles=[],
        executeur=executeur,
    )

    assert res.decision.action == "impossible"
    assert res.state == "echec"
    assert executeur.appels == []
    assert [e["id"] for e in await lister_echecs(db_conn)] == [res.run_id]


async def test_la_cible_retenue_est_recopiee_dans_la_trace(db_conn) -> None:
    """Le gabarit doit se relire dans le registre : la configuration aura changé
    le jour où l'on se demandera pourquoi cette machine a été montée ainsi."""
    sub = await _seed(db_conn)

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="dedie",
        host_profiles=PROFILS,
        executeur=ExecuteurFactice(),
    )

    ligne = await lire(res.run_id or 0, db_conn)
    assert ligne is not None
    assert ligne["host_profile"] == "host-standard"
    assert ligne["machine_profile"] == "pve-4g"
    assert ligne["hypervisor"] == "pve-a"


async def test_une_machine_mutualisee_ne_recoit_aucune_ligne_de_propriete(db_conn) -> None:
    """Une machine mutualisée n'a PAS de propriétaire (migration 117).

    Le rattachement d'un abonnement au pool passe par `subscription_hosts` —
    c'est le contrat de l'`Executeur` — et JAMAIS par `host_ownership`, qui est
    la table du dédié (clé = machine, `owner_login` NOT NULL). Une ligne de
    propriété sur une machine de pool réinventerait le propriétaire que le
    modèle a supprimé.
    """
    sub = await _seed(db_conn, hebergement="mutualise")
    await _seed_host_mutualise(db_conn, nom="mut-01", owner="alice", capacite=4)

    class ExecuteurConforme(ExecuteurFactice):
        """Persiste le rattachement comme le contrat l'exige — côté pool."""

        async def assigner_host(
            self, *, subscription_id, owner_login, offer_slug, host_name
        ) -> HostProvisionne:
            await rattacher(subscription_id, host_name, 1, db_conn)
            return HostProvisionne(host_name=host_name)

    res = await traiter(
        db_conn,
        subscription_id=sub,
        provider_event_id="evt_1",
        evenement="debut_essai",
        owner_login="alice",
        offer_slug="standard",
        hosting_type="mutualise",
        host_profiles=PROFILS,
        executeur=ExecuteurConforme(),
    )

    assert res.state == "fait"
    assert await a_deja_une_machine(sub, db_conn) is True
    proprietes = (await db_conn.execute(host_ownership.select())).all()
    assert proprietes == []
