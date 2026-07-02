"""Tests de la couche persistance GlobalConfig (Tour 1).

Couvre : round-trip save/load, cache warm/invalidate, idempotence,
hosts + hypervisors + hypervisor_types persistés et récupérés.
"""
from __future__ import annotations

import pytest

from portal.config.models import GlobalConfig
from portal.db.global_config import (
    get_cached_global,
    invalidate_cache,
    load_global_db,
    save_global_db,
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
            },
            "hypervisor_types": [
                {
                    "name": "proxmox",
                    "label": "Proxmox VE",
                    "add_script": "add.sh",
                    "destroy_script": "del.sh",
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
                    "password": "",
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


# ─── Idempotence (double save = update, pas d'erreur de contrainte) ────────────


@pytest.mark.asyncio
async def test_double_save_updates_in_place(db_conn, minimal_cfg, full_cfg):
    await save_global_db(minimal_cfg, db_conn)
    await save_global_db(full_cfg, db_conn)

    result = await load_global_db(db_conn)
    assert result.version == "2"
    assert len(result.hosts) == 1


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
async def test_save_global_db_updates_cache(db_conn, minimal_cfg):
    invalidate_cache()
    await save_global_db(minimal_cfg, db_conn)

    cached = get_cached_global()
    assert cached.version == "1"


# ─── Erreur si table vide ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_raises_if_no_row(db_conn):
    with pytest.raises(FileNotFoundError, match="global_config"):
        await load_global_db(db_conn)
