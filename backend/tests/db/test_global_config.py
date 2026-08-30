"""Tests de la couche persistance GlobalConfig (Tour 1).

Couvre : round-trip save/load, cache warm/invalidate, idempotence,
hosts + hypervisors + hypervisor_types persistés et récupérés.
"""

from __future__ import annotations

import asyncio

import pytest

from portal.config.models import GlobalConfig, HostConfig
from portal.db.global_config import (
    get_cached_global,
    get_optional_cached_global,
    invalidate_cache,
    load_global_db,
    save_global_db,
    set_cached_global,
    warm_global_cache,
)

# ─── Fixture GlobalConfig minimale ────────────────────────────────────────────


@pytest.fixture
def minimal_cfg() -> GlobalConfig:
    return GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {
                "base_domain": "dev.yoops.org",
                "external_url": "https://dev.yoops.org",
            },
            "auth": {
                "oidc": {
                    "issuer": "https://security.yoops.org/realms/yoops",
                    "client_id": "workspace-portal",
                    "client_secret": "",
                }
            },
        }
    )


@pytest.fixture
def full_cfg() -> GlobalConfig:
    return GlobalConfig.model_validate(
        {
            "version": "2",
            "server": {
                "listen": "0.0.0.0:9090",
                "base_domain": "test.example.com",
                "external_url": "https://test.example.com",
                "dev_mode": True,
                "workspace_host": "192.168.1.99",
                "log": {"level": "debug", "format": "json", "output": "/tmp/log"},
            },
            "auth": {
                "oidc": {
                    "issuer": "https://auth.example.com",
                    "client_id": "my-client",
                    "client_secret": "s3cr3t",
                    "scopes": ["openid", "email"],
                    "role_claim": "groups",
                    "admin_role": "superadmin",
                    "user_role": "user",
                    "username_claim": "login",
                }
            },
            "secrets": {
                "backend": "harpocrate",
                "harpocrate": {
                    "url": "https://vault.example.com",
                    "api_key": "hrpv_1_test",
                    "base_path": "myapp",
                },
            },
            "devpod": {
                "binary": "/opt/devpod",
                "client_cert_path": "/data/certs",
                "defaults": {"ide": "vscode", "idle_timeout": "4h", "dotfiles": "https://gh.io"},
            },
            "caddy": {"admin_api": "http://caddy:2019", "portal_host": "myportal"},
            "cloudflare_manager": {"url": "https://cf.example.com", "api_key": "cfkey"},
            "logs": {
                "enabled": True,
                "loki_push_url": "http://loki:3100/loki/api/v1/push",
                "loki_query_url": "http://loki:3100",
                "grafana_url": "http://192.168.10.196:3001",
                "module": "devpod-test",
                "push_token": "${vault://bloc/loki-token}",
                "grafana_oauth_client_secret": "gf-secret-xyz",
            },
            "events_producer": {
                "enabled": True,
                "workflow_base_url": "https://workflow.example.com",
                "source_id": "11111111-2222-3333-4444-555555555555",
                "secret_slug": "wf-hmac-test",
                "source_uri": "urn:yoops:test",
                "events": ["workspace.created", "workspace.deleted"],
            },
            "bastion": {
                "enabled": True,
                "api_url": "https://termix.example.com",
                "host": "portal",
                "port": 2223,
                "role": "devs",
                "apikey_secret": "termix-apikey-test",
            },
            "hypervisor_types": [
                {
                    "name": "proxmox",
                    "label": "Proxmox VE",
                    "add_script": "add.sh",
                    "destroy_script": "del.sh",
                    "actions": [
                        {
                            "label": "Increase memory +1G",
                            "slug": "proxmox-increase-memory-1g",
                            "script": "https://raw.example.com/mem.json",
                            "cible": "machine",
                        },
                        {
                            "label": "Inventaire",
                            "slug": "proxmox-inventaire",
                            "script": "https://raw.example.com/inv.json",
                            "cible": "hyperviseur",
                        },
                    ],
                    "variables": [
                        {"label": "Capacité", "slug": "capacity_workspaces", "type": "int"},
                    ],
                }
            ],
            "hypervisors": [
                {
                    "name": "pve01",
                    "address": "192.168.1.10",
                    "ssh_user": "root",
                    "ssh_port": 22,
                    "ssh_key_path": "/data/keys/pve01",
                    "pve_node": "pve",
                    "hypervisor_type": "proxmox",
                }
            ],
            "hosts": [
                {
                    "name": "worker01",
                    "default": True,
                    "type": "docker-tls",
                    "docker_host": "tcp://192.168.1.20:2376",
                    "address": "192.168.1.20",
                    "host_cert_slug": "hosts/worker01",
                    "profile_slug": "gros-noeud",
                    "capacity_workspaces": 12,
                    "accepts_mutualise": True,
                }
            ],
        }
    )


# ─── Tests round-trip ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_load_minimal(db_conn, minimal_cfg):
    await save_global_db(minimal_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.version == "1"
    assert result.server.base_domain == "dev.yoops.org"
    assert result.auth.oidc.issuer == "https://security.yoops.org/realms/yoops"
    assert result.hosts == []
    assert result.hypervisors == []
    assert result.hypervisor_types == []


@pytest.mark.asyncio
async def test_save_and_load_full(db_conn, full_cfg):
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.version == "2"
    assert result.server.listen == "0.0.0.0:9090"
    assert result.server.dev_mode is True
    assert result.server.workspace_host == "192.168.1.99"
    assert result.server.log.level == "debug"
    assert result.server.log.format == "json"
    assert result.auth.oidc.client_secret == "s3cr3t"
    assert result.auth.oidc.scopes == ["openid", "email"]
    assert result.secrets.backend == "harpocrate"
    assert result.secrets.harpocrate.url == "https://vault.example.com"
    assert result.devpod.binary == "/opt/devpod"
    assert result.devpod.defaults.idle_timeout == "4h"
    assert result.caddy.portal_host == "myportal"
    assert result.cloudflare_manager.api_key == "cfkey"
    assert result.logs.enabled is True
    assert result.logs.loki_push_url == "http://loki:3100/loki/api/v1/push"
    assert result.logs.grafana_url == "http://192.168.10.196:3001"
    assert result.logs.module == "devpod-test"
    assert result.logs.push_token == "${vault://bloc/loki-token}"
    assert result.logs.grafana_oauth_client_secret == "gf-secret-xyz"


@pytest.mark.asyncio
async def test_logs_config_defaults_when_unset(db_conn, minimal_cfg):
    # minimal_cfg ne fixe pas `logs` → LogsConfig() par défaut, round-trip
    # via des colonnes NOT NULL (chaînes vides converties en None à la lecture).
    await save_global_db(minimal_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.logs.enabled is False
    assert result.logs.loki_push_url is None
    assert result.logs.loki_query_url is None
    assert result.logs.grafana_url is None
    assert result.logs.module == "devpod"
    assert result.logs.push_token is None
    assert result.logs.grafana_oauth_client_secret is None


@pytest.mark.asyncio
async def test_logs_config_survives_double_save(db_conn, minimal_cfg, full_cfg):
    # Régression du bug initial : `logs` était accepté par PUT /admin/config
    # mais jamais persisté → perdu au redémarrage suivant du portail.
    await save_global_db(minimal_cfg, db_conn)
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.logs.enabled is True
    assert result.logs.grafana_url == "http://192.168.10.196:3001"


@pytest.mark.asyncio
async def test_bastion_config_defaults_when_unset(db_conn, minimal_cfg):
    await save_global_db(minimal_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.bastion.enabled is False
    assert result.bastion.api_url == ""
    assert result.bastion.host == ""
    assert result.bastion.port == 2222
    assert result.bastion.role == ""
    assert result.bastion.apikey_secret == "termix-apikey"


@pytest.mark.asyncio
async def test_bastion_config_survives_double_save(db_conn, minimal_cfg, full_cfg):
    # Régression : `bastion` était accepté par PUT /admin/bastion-config mais
    # jamais persisté → config perdue au redémarrage suivant du portail
    # (provisioning Termix silencieusement inactif, sshd non redémarré).
    await save_global_db(minimal_cfg, db_conn)
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.bastion.enabled is True
    assert result.bastion.api_url == "https://termix.example.com"
    assert result.bastion.host == "portal"
    assert result.bastion.port == 2223
    assert result.bastion.role == "devs"
    assert result.bastion.apikey_secret == "termix-apikey-test"


@pytest.mark.asyncio
async def test_events_producer_defaults_when_unset(db_conn, minimal_cfg):
    await save_global_db(minimal_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.events_producer.enabled is False
    assert result.events_producer.workflow_base_url == ""
    assert result.events_producer.source_id == ""
    assert result.events_producer.secret_slug == "workflow_events_hmac"
    assert result.events_producer.source_uri == "urn:yoops:devpod"
    assert result.events_producer.events == []


@pytest.mark.asyncio
async def test_events_producer_survives_double_save(db_conn, minimal_cfg, full_cfg):
    # Régression : même trou de persistance que `bastion` (section RAM-only).
    await save_global_db(minimal_cfg, db_conn)
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert result.events_producer.enabled is True
    assert result.events_producer.workflow_base_url == "https://workflow.example.com"
    assert result.events_producer.source_id == "11111111-2222-3333-4444-555555555555"
    assert result.events_producer.secret_slug == "wf-hmac-test"
    assert result.events_producer.source_uri == "urn:yoops:test"
    assert result.events_producer.events == ["workspace.created", "workspace.deleted"]


@pytest.mark.asyncio
async def test_hosts_round_trip(db_conn, full_cfg):
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert len(result.hosts) == 1
    h = result.hosts[0]
    assert h.name == "worker01"
    assert h.default is True
    assert h.type == "docker-tls"
    assert h.docker_host == "tcp://192.168.1.20:2376"


@pytest.mark.asyncio
async def test_host_capacite_et_provenance_round_trip(db_conn, full_cfg):
    """La capacite d'accueil et le profil d'origine survivent au rechargement.

    Ce sont des donnees d'EXPLOITATION : sans elles, le portail ne sait ni
    combien de workspaces la machine tient, ni sur quel profil elle a ete
    montee. Les perdre en base revient a ne jamais les avoir saisies.
    """
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    h = result.hosts[0]
    assert h.profile_slug == "gros-noeud"
    assert h.capacity_workspaces == 12
    assert h.accepts_mutualise is True


@pytest.mark.asyncio
async def test_host_sans_capacite_reste_sans_capacite(db_conn, minimal_cfg):
    """`None` = non renseigne, et le rechargement ne l'invente pas.

    Un host enrole a la main n'a pas de profil : sa capacite est inconnue tant
    que l'exploitant ne l'a pas dite. La confondre avec zero interdirait tout
    workspace ; la confondre avec l'infini ferait planter la machine.
    """
    cfg = minimal_cfg.model_copy(update={"hosts": [HostConfig(name="brut", type="ssh")]})
    await save_global_db(cfg, db_conn)
    result = await load_global_db(db_conn)

    h = result.hosts[0]
    assert h.capacity_workspaces is None
    assert h.accepts_mutualise is False
    assert h.profile_slug == ""


@pytest.mark.asyncio
async def test_hypervisors_round_trip(db_conn, full_cfg):
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert len(result.hypervisors) == 1
    n = result.hypervisors[0]
    assert n.name == "pve01"
    assert n.address == "192.168.1.10"
    assert n.hypervisor_type == "proxmox"


@pytest.mark.asyncio
async def test_hypervisor_types_round_trip(db_conn, full_cfg):
    await save_global_db(full_cfg, db_conn)
    result = await load_global_db(db_conn)

    assert len(result.hypervisor_types) == 1
    ht = result.hypervisor_types[0]
    assert ht.name == "proxmox"
    assert ht.label == "Proxmox VE"
    assert ht.add_script == "add.sh"


@pytest.mark.asyncio
async def test_actions_et_variables_survivent_a_un_rechargement_depuis_la_base(db_conn, full_cfg):
    """Regression : les deux listes n'etaient portees par aucune colonne.

    Le test passe DELIBEREMENT par la base — save puis `warm_global_cache`, qui
    relit — et non par la reponse de l'enregistrement : c'est precisement parce
    que le cache memoire repondait juste que la perte est restee invisible
    jusqu'au redemarrage suivant du portail.
    """
    invalidate_cache()
    await save_global_db(full_cfg, db_conn)
    await warm_global_cache(db_conn)

    ht = get_cached_global().hypervisor_types[0]
    assert [a.slug for a in ht.actions] == [
        "proxmox-increase-memory-1g",
        "proxmox-inventaire",
    ]
    assert ht.actions[0].script == "https://raw.example.com/mem.json"
    assert [a.cible for a in ht.actions] == ["machine", "hyperviseur"]
    assert [v.slug for v in ht.variables] == ["capacity_workspaces"]
    assert ht.variables[0].type == "int"


@pytest.mark.asyncio
async def test_type_anterieur_a_la_migration_relit_des_listes_vides(db_conn, minimal_cfg):
    """Ligne ecrite sans les colonnes de la migration 122 : listes vides, pas d'erreur.

    C'est l'etat de tous les types deja enregistres le jour du deploiement.
    """
    from sqlalchemy import insert

    from portal.db.tables import hypervisor_types

    await save_global_db(minimal_cfg, db_conn)
    await db_conn.execute(
        insert(hypervisor_types).values(name="legacy", label="Ancien", add_script="add.sh")
    )

    ht = (await load_global_db(db_conn)).hypervisor_types[0]
    assert ht.name == "legacy"
    assert ht.actions == []
    assert ht.variables == []


# ─── Idempotence (double save = update, pas d'erreur de contrainte) ────────────


@pytest.mark.asyncio
async def test_double_save_updates_in_place(db_conn, minimal_cfg, full_cfg):
    await save_global_db(minimal_cfg, db_conn)
    await save_global_db(full_cfg, db_conn)

    result = await load_global_db(db_conn)
    assert result.version == "2"
    assert len(result.hosts) == 1


@pytest.mark.asyncio
async def test_save_concurrent_singleton_sans_unique_violation(db_engine_concurrent, minimal_cfg):
    """Bug 010 : deux écritures concurrentes du singleton id=1 (premier démarrage
    ou deux PUT /admin/config simultanés). La 2e transaction ne voit pas l'INSERT
    non commité de la 1re (READ COMMITTED) — elle ne doit pas lever UniqueViolation.
    Listes (hosts/hypervisors) vides : le remplacement delete+insert est hors
    périmètre ici, seul le singleton est exercé."""
    cfg2 = minimal_cfg.model_copy(deep=True)
    cfg2.version = "2"
    async with (
        db_engine_concurrent.connect() as c1,
        db_engine_concurrent.connect() as c2,
    ):
        await save_global_db(minimal_cfg, c1)

        async def _concurrent_save() -> None:
            await save_global_db(cfg2, c2)
            await c2.commit()

        task = asyncio.create_task(_concurrent_save())
        await asyncio.sleep(0.3)
        await c1.commit()
        await asyncio.wait_for(task, timeout=10)

    async with db_engine_concurrent.connect() as c3:
        result = await load_global_db(c3)
    assert result is not None
    assert result.version == "2"


# ─── Remplacement complet des listes (delete + insert) ───────────────────────


@pytest.mark.asyncio
async def test_save_replaces_hosts_list(db_conn, full_cfg, minimal_cfg):
    await save_global_db(full_cfg, db_conn)
    assert len((await load_global_db(db_conn)).hosts) == 1

    await save_global_db(minimal_cfg, db_conn)
    assert (await load_global_db(db_conn)).hosts == []


# ─── Cache warm / invalidate ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warm_cache_populates_get_cached(db_conn, minimal_cfg):
    invalidate_cache()
    await save_global_db(minimal_cfg, db_conn)
    await warm_global_cache(db_conn)

    cached = get_cached_global()
    assert cached.server.base_domain == "dev.yoops.org"


@pytest.mark.asyncio
async def test_get_cached_raises_before_warm(db_conn):
    invalidate_cache()
    with pytest.raises(RuntimeError, match="non initialisé"):
        get_cached_global()


@pytest.mark.asyncio
async def test_save_global_db_does_not_touch_cache(db_conn, minimal_cfg):
    """Bug 034 : save_global_db (couche DB, encore dans la transaction de
    l'appelant) ne doit jamais peupler le cache lui-même — sinon un COMMIT qui
    échoue à la sortie du bloc `begin()` laisse un cache fantôme non commité.
    Seul config.store.save_global le fait, après un commit réussi."""
    invalidate_cache()
    await save_global_db(minimal_cfg, db_conn)

    assert get_optional_cached_global() is None


def test_set_cached_global_populates_cache(minimal_cfg):
    invalidate_cache()
    set_cached_global(minimal_cfg)

    cached = get_cached_global()
    assert cached.version == "1"


# ─── Erreur si table vide ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_rend_none_si_pas_de_ligne(db_conn):
    """Base vide : `load_global_db` rend None, il ne leve pas.

    Le refus a demenage d'un cran : c'est `get_cached_global()` qui refuse une
    base sans configuration, la ou `get_optional_cached_global()` accepte None.
    Ce test decrivait l'ancien contrat.
    """
    assert await load_global_db(db_conn) is None
