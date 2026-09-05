"""L'exécuteur Proxmox : préparation, persistance et rattachement — sans SSH.

Les trois opérations d'infrastructure (`_spec`, `_prochain_vmid`,
`_executer_commandes`) sont surchargées : ce qui se prouve ici, c'est que la
machine et son rattachement sont écrits comme le modèle l'exige — propriété
pour le dédié, part pour le pool, capacité lue du profil de host — et que les
échecs sont exploitables. Le vrai clone relève du test d'intégration sur test1.

Ces tests passent par `db_engine` et des transactions COURTES, pas par
`db_conn` : l'exécuteur ouvre ses propres connexions sur le moteur, et le
moteur de test n'en a qu'une — la garder ouverte pendant l'appel serait un
interblocage, pas un test.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import insert, select

from portal.billing.cible import Cible
from portal.billing.executeur_proxmox import ExecuteurProxmox, ProvisioningImpossible
from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    Hypervisor,
    OidcConfig,
    ServerConfig,
)
from portal.db.tables import (
    countries,
    host_ownership,
    host_profiles,
    hosts,
    machine_profiles,
    offers,
    subscription_hosts,
    subscriptions,
    users,
)

CIBLE = Cible(
    host_profile="host-standard",
    machine_profile="pve-4g",
    hypervisor="pve-a",
    noeud="pve",
)

SPEC = {
    "args": [
        {"arg": "NEW_VMID", "identifier": True},
        {"arg": "NODE_NAME"},
        {"arg": "TEMPLATE", "default": "8000"},
    ],
    "commands": ["bash clone.sh {NEW_VMID} {NODE_NAME} --template {TEMPLATE}"],
}


class ExecuteurBanc(ExecuteurProxmox):
    """Infra factice : spec figée, VMID 4321, sortie de script contrôlée."""

    def __init__(self, *, sortie: str | None = None) -> None:
        self.commandes: list[str] = []
        self.sortie = sortie if sortie is not None else json.dumps(
            {"name": "", "address": "10.0.0.42", "ssh_user": "debian", "vmid": "4321"}
        )

    async def _spec(self, node, cfg):
        return SPEC

    async def _prochain_vmid(self, node):
        return "4321"

    async def _executer_commandes(self, node, commandes, *, vmid, nom):
        self.commandes = commandes
        return self.sortie


@pytest.fixture(autouse=True)
def _environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration globale et settings, sans fichier ni env."""
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url="https://portail.test"),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisors=[
            Hypervisor(
                name="pve-a",
                address="10.0.0.1",
                ssh_key_path="/dev/null",
                pve_node="pve",
                hypervisor_type="proxmox4vm",
            )
        ],
    )
    monkeypatch.setattr("portal.config.store.load_global", lambda *a, **k: cfg)

    class _Settings:
        portal_api_key = "clef-de-test"

    monkeypatch.setattr("portal.settings.get_settings", lambda: _Settings())


async def _seed(
    engine, *, quota_offre: int | None = 3, capacite: str | None = "8", max_memory: str = "4g"
) -> str:
    async with engine.begin() as conn:
        await conn.execute(
            insert(users).values(
                login="alice",
                version="1",
                secret_ns=str(uuid.uuid4()),
                default_ide="openvscode",
                default_idle_timeout="2h",
                harpocrate_api_key="",
            )
        )
        await conn.execute(insert(countries).values(code="FR", label="France"))
        await conn.execute(
            insert(offers).values(slug="standard", label="Standard", max_workspaces=quota_offre)
        )
        await conn.execute(
            insert(machine_profiles).values(
                slug="pve-4g",
                label="4 Go",
                hypervisor_type="proxmox4vm",
                params={"TEMPLATE": "9001"},
            )
        )
        variables: dict[str, str] = {}
        if capacite is not None:
            variables["capacity_workspaces"] = capacite
        if max_memory:
            variables["max_memory"] = max_memory
        await conn.execute(
            insert(host_profiles).values(
                slug="host-standard",
                label="Standard",
                machine_profile="pve-4g",
                variables=variables,
            )
        )
        sid = str(uuid.uuid4())
        await conn.execute(
            insert(subscriptions).values(
                id=sid,
                login="alice",
                offer_slug="standard",
                state="essai",
                country_code="FR",
                currency="EUR",
                amount_minor=0,
            )
        )
    return sid


async def _lignes(engine, table):
    async with engine.begin() as conn:
        return (await conn.execute(select(table))).mappings().all()


async def test_une_vm_dediee_est_montee_possedee_et_rattachee(db_engine) -> None:
    sid = await _seed(db_engine)
    banc = ExecuteurBanc()

    resultat = await banc.creer_vm_dediee(
        subscription_id=sid, owner_login="alice", offer_slug="standard", noeud="pve", cible=CIBLE
    )

    assert resultat.host_name == "ded-4321"
    # La capacité vient du PROFIL DE HOST, pas d'une constante.
    assert resultat.capacity_workspaces == 8
    (hote,) = await _lignes(db_engine, hosts)
    assert hote["usage"] == "workspaces"
    assert hote["accepts_mutualise"] is False
    assert hote["capacity_workspaces"] == 8
    # Le plafond mémoire du profil de host est recopié sur le nœud (provenance).
    assert hote["max_memory"] == "4g"
    assert hote["hypervisor"] == "pve-a"
    (propriete,) = await _lignes(db_engine, host_ownership)
    assert propriete["owner_login"] == "alice"
    # Quota commercial FIGÉ au provisionnement.
    assert propriete["offer_max_workspaces"] == 3
    (part,) = await _lignes(db_engine, subscription_hosts)
    assert part["subscription_id"] == sid
    # En dédié : aucun plafond commercial sur la part, la capacité gouverne.
    assert part["allocated_workspaces"] is None


async def test_un_host_mutualise_entre_au_pool_sans_proprietaire(db_engine) -> None:
    sid = await _seed(db_engine)
    banc = ExecuteurBanc()

    resultat = await banc.creer_host_mutualise(
        subscription_id=sid, owner_login="alice", offer_slug="standard", cible=CIBLE
    )

    assert resultat.host_name == "mut-4321"
    (hote,) = await _lignes(db_engine, hosts)
    assert hote["accepts_mutualise"] is True
    # Une machine du pool n'a PAS de propriétaire (migration 117).
    assert await _lignes(db_engine, host_ownership) == []
    (part,) = await _lignes(db_engine, subscription_hosts)
    assert part["allocated_workspaces"] == 3


async def test_les_arguments_du_script_sont_resolus(db_engine) -> None:
    """VMID alloué, nom dérivé, défauts de spec surchargés par le profil."""
    sid = await _seed(db_engine)
    banc = ExecuteurBanc()

    await banc.creer_vm_dediee(
        subscription_id=sid, owner_login="alice", offer_slug="standard", noeud="pve", cible=CIBLE
    )

    assert banc.commandes == ["bash clone.sh 4321 ded-4321 --template 9001"]


async def test_assigner_donne_sa_part_sans_creer_de_machine(db_engine) -> None:
    sid = await _seed(db_engine)
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(hosts).values(
                name="mut-01", type="docker-tls", accepts_mutualise=True, capacity_workspaces=6
            )
        )
    banc = ExecuteurBanc()

    resultat = await banc.assigner_host(
        subscription_id=sid, owner_login="alice", offer_slug="standard", host_name="mut-01"
    )

    assert resultat.host_name == "mut-01"
    assert resultat.capacity_workspaces == 6
    (part,) = await _lignes(db_engine, subscription_hosts)
    assert part["host_name"] == "mut-01"
    assert part["allocated_workspaces"] == 3
    assert len(await _lignes(db_engine, hosts)) == 1


async def test_une_sortie_sans_json_est_un_echec_exploitable(db_engine) -> None:
    sid = await _seed(db_engine)
    banc = ExecuteurBanc(sortie="qm clone: storage 'local' full\n")

    with pytest.raises(ProvisioningImpossible, match="JSON"):
        await banc.creer_vm_dediee(
            subscription_id=sid,
            owner_login="alice",
            offer_slug="standard",
            noeud="pve",
            cible=CIBLE,
        )
    # Rien n'est persisté : ni machine, ni rattachement.
    assert await _lignes(db_engine, hosts) == []
    assert await _lignes(db_engine, subscription_hosts) == []


async def test_une_capacite_non_declaree_reste_inconnue(db_engine) -> None:
    """`None` = non renseigné — jamais zéro, jamais l'infini."""
    sid = await _seed(db_engine, capacite=None)
    banc = ExecuteurBanc()

    resultat = await banc.creer_vm_dediee(
        subscription_id=sid, owner_login="alice", offer_slug="standard", noeud="pve", cible=CIBLE
    )

    assert resultat.capacity_workspaces is None
    (hote,) = await _lignes(db_engine, hosts)
    assert hote["capacity_workspaces"] is None
