from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


def get_optional_cached_global() -> GlobalConfig | None:
    """Retourne la GlobalConfig depuis le cache RAM, ou None si absente/non initialisée."""
    return _cache


async def warm_global_cache(conn: AsyncConnection) -> None:
    """Charge la GlobalConfig depuis la DB et peuple le cache. Appelé au lifespan."""
    global _cache
    _cache = await _load_from_db(conn)
    if _cache is None:
        _log.warning(
            "global_config_empty",
            msg="Aucune GlobalConfig en base — premier démarrage, configurez via /admin/config",
        )
    else:
        _log.info("global_config_cache_warmed")


def invalidate_cache() -> None:
    """Invalide le cache (utilisé dans les tests)."""
    global _cache
    _cache = None


def set_cached_global(cfg: GlobalConfig) -> None:
    """Peuple le cache RAM sans toucher la DB.

    À appeler seulement après un COMMIT réussi (config/store.py::save_global) —
    jamais depuis l'intérieur d'une transaction : si le COMMIT échoue à la sortie
    du bloc `begin()`, la DB rollback mais un cache déjà peuplé continuerait de
    servir un état fantôme jusqu'au prochain redémarrage (bug 034).
    """
    global _cache
    _cache = cfg


async def load_global_db(conn: AsyncConnection) -> GlobalConfig | None:
    """Lecture depuis la DB (sans cache). Utilisé par warm_global_cache et les tests."""
    return await _load_from_db(conn)


async def save_global_db(cfg: GlobalConfig, conn: AsyncConnection) -> None:
    """Écrit la GlobalConfig en DB.

    Ne touche PAS le cache : `conn` est encore dans la transaction de l'appelant
    à ce stade, le COMMIT n'a pas encore eu lieu. Le cache est peuplé par
    l'appelant (config/store.py::save_global) après la sortie réussie du bloc
    `begin()` — voir set_cached_global (bug 034).
    """
    await _write_to_db(cfg, conn)
    _log.info("global_config_saved")


# ─── Fonctions internes ───────────────────────────────────────────────────────


async def _load_from_db(conn: AsyncConnection) -> GlobalConfig | None:
    row_result = await conn.execute(select(global_config).where(global_config.c.id == 1))
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
    return GlobalConfig.model_validate(
        {
            "version": row["version"],
            "server": {
                "listen": row["listen"],
                "base_domain": row["base_domain"],
                "external_url": row["external_url"],
                "dev_mode": row["dev_mode"],
                "workspace_host": row["workspace_host"],
                "local_domain": row["local_domain"],
                "vs_proxy_domain": row["vs_proxy_domain"],
                "cookie_domain": row["cookie_domain"],
                "session_max_age": row["session_max_age"],
                "session_absolute_max_age": row["session_absolute_max_age"],
                "log": {
                    "level": row["log_level"],
                    "format": row["log_format"],
                    "output": row["log_output"],
                },
            },
            "logs": {
                "enabled": row["logs_enabled"],
                "loki_push_url": row["logs_loki_push_url"] or None,
                "loki_query_url": row["logs_loki_query_url"] or None,
                "metrics_push_url": row["logs_metrics_push_url"] or None,
                "grafana_url": row["logs_grafana_url"] or None,
                "module": row["logs_module"],
                "push_token": row["logs_push_token"] or None,
                "grafana_oauth_client_id": row["logs_grafana_oauth_client_id"],
                "grafana_oauth_client_secret": row["logs_grafana_oauth_client_secret"] or None,
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
                    "allow_local_auth": row.get("oidc_allow_local_auth", True),
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
            "events_producer": {
                "enabled": row["events_enabled"],
                "workflow_base_url": row["events_workflow_base_url"],
                "source_id": row["events_source_id"],
                "secret_slug": row["events_secret_slug"],
                "source_uri": row["events_source_uri"],
                "events": list(row["events_types"]),
            },
            "bastion": {
                "enabled": row["bastion_enabled"],
                "api_url": row["bastion_api_url"],
                "host": row["bastion_host"],
                "port": row["bastion_port"],
                "role": row["bastion_role"],
                "apikey_secret": row["bastion_apikey_secret"],
            },
            "hypervisor_types": [_ht_row_to_dict(r) for r in ht_rows],
            "hypervisors": [_hyp_row_to_dict(r) for r in hyp_rows],
            "hosts": [_host_row_to_dict(r) for r in host_rows],
        }
    )


def _ht_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "label": row["label"],
        "add_script": row["add_script"],
        "destroy_script": row["destroy_script"],
        "test_host_params": dict(row["test_host_params"] or {}),
        # `or []` couvre les lignes anterieures a la migration 122, dont la
        # colonne peut etre NULL : une declaration absente est une liste vide.
        "actions": list(row["actions"] or []),
        "variables": list(row["variables"] or []),
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
    }


def _host_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "default": row["is_default"],
        "type": row["type"],
        "docker_host": row["docker_host"],
        "address": row["address"],
        "proxmox_node": row["proxmox_node"],
        "vmid": row["vmid"],
        "ci_password_secret_slug": row["ci_password_secret_slug"],
        "host_cert_slug": row["host_cert_slug"],
        "docker_cert_slug": row["docker_cert_slug"],
        "storage_type": row["storage_type"],
        "vault_identifier": row["vault_identifier"],
        "usage": row["usage"],
        "profile_slug": row["profile_slug"],
        "capacity_workspaces": row["capacity_workspaces"],
        "accepts_mutualise": row["accepts_mutualise"],
        "hypervisor": row["hypervisor"],
        "max_memory": row["max_memory"],
    }


async def _write_to_db(cfg: GlobalConfig, conn: AsyncConnection) -> None:
    scalars = _cfg_to_scalars(cfg)

    # Upsert atomique du singleton id=1 (bug 010) : le check-then-insert laissait
    # deux transactions concurrentes tenter chacune l'INSERT → UniqueViolation.
    await conn.execute(
        pg_insert(global_config)
        .values(**scalars)
        .on_conflict_do_update(
            index_elements=[global_config.c.id],
            set_={k: v for k, v in scalars.items() if k != "id"},
        )
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
        "local_domain": cfg.server.local_domain,
        "vs_proxy_domain": cfg.server.vs_proxy_domain,
        "cookie_domain": cfg.server.cookie_domain,
        "session_max_age": cfg.server.session_max_age,
        "session_absolute_max_age": cfg.server.session_absolute_max_age,
        "log_level": cfg.server.log.level,
        "log_format": cfg.server.log.format,
        "log_output": cfg.server.log.output,
        "logs_enabled": cfg.logs.enabled,
        "logs_loki_push_url": cfg.logs.loki_push_url or "",
        "logs_loki_query_url": cfg.logs.loki_query_url or "",
        "logs_metrics_push_url": cfg.logs.metrics_push_url or "",
        "logs_grafana_url": cfg.logs.grafana_url or "",
        "logs_module": cfg.logs.module,
        "logs_push_token": cfg.logs.push_token or "",
        "logs_grafana_oauth_client_id": cfg.logs.grafana_oauth_client_id,
        "logs_grafana_oauth_client_secret": cfg.logs.grafana_oauth_client_secret or "",
        "oidc_issuer": cfg.auth.oidc.issuer,
        "oidc_client_id": cfg.auth.oidc.client_id,
        "oidc_client_secret": cfg.auth.oidc.client_secret,
        "oidc_scopes": list(cfg.auth.oidc.scopes),
        "oidc_role_claim": cfg.auth.oidc.role_claim,
        "oidc_admin_role": cfg.auth.oidc.admin_role,
        "oidc_user_role": cfg.auth.oidc.user_role,
        "oidc_username_claim": cfg.auth.oidc.username_claim,
        "oidc_allow_local_auth": cfg.auth.oidc.allow_local_auth,
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
        "events_enabled": cfg.events_producer.enabled,
        "events_workflow_base_url": cfg.events_producer.workflow_base_url,
        "events_source_id": cfg.events_producer.source_id,
        "events_secret_slug": cfg.events_producer.secret_slug,
        "events_source_uri": cfg.events_producer.source_uri,
        "events_types": list(cfg.events_producer.events),
        "bastion_enabled": cfg.bastion.enabled,
        "bastion_api_url": cfg.bastion.api_url,
        "bastion_host": cfg.bastion.host,
        "bastion_port": cfg.bastion.port,
        "bastion_role": cfg.bastion.role,
        "bastion_apikey_secret": cfg.bastion.apikey_secret,
    }


def _ht_to_row(ht: HypervisorType) -> dict[str, Any]:
    return {
        "name": ht.name,
        "label": ht.label,
        "add_script": ht.add_script,
        "destroy_script": ht.destroy_script,
        "test_host_params": dict(ht.test_host_params),
        # `model_dump` et non un dict fabrique a la main : un champ ajoute plus
        # tard au modele suit tout seul, au lieu d'etre perdu en silence.
        "actions": [a.model_dump(mode="json") for a in ht.actions],
        "variables": [v.model_dump(mode="json") for v in ht.variables],
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
    }


def _host_to_row(h: HostConfig) -> dict[str, Any]:
    return {
        "name": h.name,
        "is_default": h.default,
        "type": h.type,
        "docker_host": h.docker_host,
        "address": h.address,
        "proxmox_node": h.proxmox_node,
        "vmid": h.vmid,
        "ci_password_secret_slug": h.ci_password_secret_slug,
        "host_cert_slug": h.host_cert_slug,
        "docker_cert_slug": h.docker_cert_slug,
        "storage_type": h.storage_type,
        "vault_identifier": h.vault_identifier,
        "usage": h.usage,
        "profile_slug": h.profile_slug,
        "capacity_workspaces": h.capacity_workspaces,
        "accepts_mutualise": h.accepts_mutualise,
        "hypervisor": h.hypervisor,
        "max_memory": h.max_memory,
    }
