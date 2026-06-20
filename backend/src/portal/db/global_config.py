from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.config.models import GlobalConfig, HostConfig, Hypervisor, HypervisorType

from .tables import global_config, hosts, hypervisor_types, hypervisors

_log = structlog.get_logger(__name__)

# Cache module-level : peuplé au démarrage, invalidé à chaque écriture.
# En multi-worker, chaque worker a son propre cache — acceptable pour un singleton
# dont les écritures sont rares (identique au cache OpenVSX existant).
_cache: GlobalConfig | None = None


def get_cached_global() -> GlobalConfig:
    """Retourne la GlobalConfig depuis le cache RAM. Raise si non initialisé."""
    if _cache is None:
        raise RuntimeError(
            "GlobalConfig non initialisé. "
            "warm_global_cache() doit être appelé au démarrage du lifespan."
        )
    return _cache


async def warm_global_cache(conn: AsyncConnection) -> None:
    """Charge la GlobalConfig depuis la DB et peuple le cache. Appelé au lifespan."""
    global _cache
    _cache = await _load_from_db(conn)
    if _cache is None:
        _log.warning("global_config_empty", msg="Aucune GlobalConfig en base — premier démarrage, configurez via /admin/config")
    else:
        _log.info("global_config_cache_warmed")


def invalidate_cache() -> None:
    """Invalide le cache (utilisé dans les tests)."""
    global _cache
    _cache = None


async def load_global_db(conn: AsyncConnection) -> GlobalConfig | None:
    """Lecture depuis la DB (sans cache). Utilisé par warm_global_cache et les tests."""
    return await _load_from_db(conn)


async def save_global_db(cfg: GlobalConfig, conn: AsyncConnection) -> None:
    """Écrit la GlobalConfig en DB et met à jour le cache."""
    global _cache
    await _write_to_db(cfg, conn)
    _cache = cfg
    _log.info("global_config_saved")


# ─── Fonctions internes ───────────────────────────────────────────────────────


async def _load_from_db(conn: AsyncConnection) -> GlobalConfig | None:
    row_result = await conn.execute(
        select(global_config).where(global_config.c.id == 1)
    )
    row = row_result.mappings().one_or_none()
    if row is None:
        return None

    ht_rows = (await conn.execute(select(hypervisor_types))).mappings().all()
    hyp_rows = (await conn.execute(select(hypervisors))).mappings().all()
    host_rows = (await conn.execute(select(hosts))).mappings().all()

    return _build_global_config(
        dict(row),
        [dict(r) for r in ht_rows],
        [dict(r) for r in hyp_rows],
        [dict(r) for r in host_rows],
    )


def _build_global_config(
    row: dict[str, Any],
    ht_rows: list[dict[str, Any]],
    hyp_rows: list[dict[str, Any]],
    host_rows: list[dict[str, Any]],
) -> GlobalConfig:
    return GlobalConfig.model_validate({
        "version": row["version"],
        "server": {
            "listen": row["listen"],
            "base_domain": row["base_domain"],
            "external_url": row["external_url"],
            "dev_mode": row["dev_mode"],
            "workspace_host": row["workspace_host"],
            "log": {
                "level": row["log_level"],
                "format": row["log_format"],
                "output": row["log_output"],
            },
        },
        "auth": {
            "oidc": {
                "issuer": row["oidc_issuer"],
                "client_id": row["oidc_client_id"],
                "client_secret": row["oidc_client_secret"],
                "scopes": list(row["oidc_scopes"]),
                "role_claim": row["oidc_role_claim"],
                "admin_role": row["oidc_admin_role"],
                "user_role": row["oidc_user_role"],
                "username_claim": row["oidc_username_claim"],
            },
        },
        "secrets": {
            "backend": row["secrets_backend"],
            "harpocrate": {
                "url": row["harpocrate_url"],
                "api_key": row["harpocrate_api_key"],
                "base_path": row["harpocrate_base_path"],
            },
        },
        "devpod": {
            "binary": row["devpod_binary"],
            "client_cert_path": row["devpod_client_cert_path"],
            "defaults": {
                "ide": row["devpod_ide"],
                "idle_timeout": row["devpod_idle_timeout"],
                "dotfiles": row["devpod_dotfiles"],
            },
        },
        "caddy": {
            "admin_api": row["caddy_admin_api"],
            "portal_host": row["caddy_portal_host"],
        },
        "cloudflare_manager": {
            "url": row["cf_url"],
            "api_key": row["cf_api_key"],
        },
        "hypervisor_types": [_ht_row_to_dict(r) for r in ht_rows],
        "hypervisors": [_hyp_row_to_dict(r) for r in hyp_rows],
        "hosts": [_host_row_to_dict(r) for r in host_rows],
    })


def _ht_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "label": row["label"],
        "add_script": row["add_script"],
        "destroy_script": row["destroy_script"],
    }


def _hyp_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "address": row["address"],
        "ssh_user": row["ssh_user"],
        "ssh_port": row["ssh_port"],
        "ssh_key_path": row["ssh_key_path"],
        "pve_node": row["pve_node"],
        "hypervisor_type": row["hypervisor_type"],
        "password": row["password"],
    }


def _host_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "default": row["is_default"],
        "type": row["type"],
        "docker_host": row["docker_host"],
        "address": row["address"],
        "key_path": row["key_path"],
        "proxmox_node": row["proxmox_node"],
        "vmid": row["vmid"],
        "ci_password": row["ci_password"],
    }


async def _write_to_db(cfg: GlobalConfig, conn: AsyncConnection) -> None:
    scalars = _cfg_to_scalars(cfg)

    existing = await conn.execute(
        select(global_config.c.id).where(global_config.c.id == 1)
    )
    if existing.one_or_none() is None:
        await conn.execute(insert(global_config).values(**scalars))
    else:
        await conn.execute(
            update(global_config).where(global_config.c.id == 1).values(**scalars)
        )

    # Remplacement complet des listes (delete + insert)
    await conn.execute(delete(hypervisor_types))
    if cfg.hypervisor_types:
        await conn.execute(
            insert(hypervisor_types),
            [_ht_to_row(ht) for ht in cfg.hypervisor_types],
        )

    await conn.execute(delete(hypervisors))
    if cfg.hypervisors:
        await conn.execute(
            insert(hypervisors),
            [_hyp_to_row(h) for h in cfg.hypervisors],
        )

    await conn.execute(delete(hosts))
    if cfg.hosts:
        await conn.execute(
            insert(hosts),
            [_host_to_row(h) for h in cfg.hosts],
        )


def _cfg_to_scalars(cfg: GlobalConfig) -> dict[str, Any]:
    return {
        "id": 1,
        "version": cfg.version,
        "listen": cfg.server.listen,
        "base_domain": cfg.server.base_domain,
        "external_url": cfg.server.external_url,
        "dev_mode": cfg.server.dev_mode,
        "workspace_host": cfg.server.workspace_host,
        "log_level": cfg.server.log.level,
        "log_format": cfg.server.log.format,
        "log_output": cfg.server.log.output,
        "oidc_issuer": cfg.auth.oidc.issuer,
        "oidc_client_id": cfg.auth.oidc.client_id,
        "oidc_client_secret": cfg.auth.oidc.client_secret,
        "oidc_scopes": list(cfg.auth.oidc.scopes),
        "oidc_role_claim": cfg.auth.oidc.role_claim,
        "oidc_admin_role": cfg.auth.oidc.admin_role,
        "oidc_user_role": cfg.auth.oidc.user_role,
        "oidc_username_claim": cfg.auth.oidc.username_claim,
        "secrets_backend": cfg.secrets.backend,
        "harpocrate_url": cfg.secrets.harpocrate.url,
        "harpocrate_api_key": cfg.secrets.harpocrate.api_key,
        "harpocrate_base_path": cfg.secrets.harpocrate.base_path,
        "devpod_binary": cfg.devpod.binary,
        "devpod_client_cert_path": cfg.devpod.client_cert_path,
        "devpod_ide": cfg.devpod.defaults.ide,
        "devpod_idle_timeout": cfg.devpod.defaults.idle_timeout,
        "devpod_dotfiles": cfg.devpod.defaults.dotfiles,
        "caddy_admin_api": cfg.caddy.admin_api,
        "caddy_portal_host": cfg.caddy.portal_host,
        "cf_url": cfg.cloudflare_manager.url,
        "cf_api_key": cfg.cloudflare_manager.api_key,
    }


def _ht_to_row(ht: HypervisorType) -> dict[str, Any]:
    return {
        "name": ht.name,
        "label": ht.label,
        "add_script": ht.add_script,
        "destroy_script": ht.destroy_script,
    }


def _hyp_to_row(h: Hypervisor) -> dict[str, Any]:
    return {
        "name": h.name,
        "address": h.address,
        "ssh_user": h.ssh_user,
        "ssh_port": h.ssh_port,
        "ssh_key_path": h.ssh_key_path,
        "pve_node": h.pve_node,
        "hypervisor_type": h.hypervisor_type,
        "password": h.password,
    }


def _host_to_row(h: HostConfig) -> dict[str, Any]:
    return {
        "name": h.name,
        "is_default": h.default,
        "type": h.type,
        "docker_host": h.docker_host,
        "address": h.address,
        "key_path": h.key_path,
        "proxmox_node": h.proxmox_node,
        "vmid": h.vmid,
        "ci_password": h.ci_password,
    }
