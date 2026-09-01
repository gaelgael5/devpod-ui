from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any, Literal

import httpx
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..bastion import servers as bastion_servers
from ..certificates.docker_bundle import (
    host_bundle_dir,
    materialize_host_bundle,
    remove_host_bundle,
)
from ..certificates.pem import normalize_pem
from ..certificates.service import CertNotFound, VaultLocked, reveal_private_key
from ..config.env_file import update_env_file
from ..config.models import GlobalConfig, HostConfig, Hypervisor, validate_network
from ..config.store import _data_root, load_global
from ..db.certificates import get_certificate
from ..db.engine import get_conn
from ..db.global_config import save_global_db, set_cached_global
from ..db.tables import harpo_certificates
from ..db.tables import workspace_status as _ws_status_table
from ..db.tables import workspaces as _ws_table
from ..db.workflow_outbox import enqueue as outbox_enqueue
from ..events.egress import (
    compute_signature,
    post_event,
    reconcile_workflow_producer,
    serialize_envelope,
)
from ..events.models import EVENT_TYPES
from ..events.producer import build_test_envelope
from ..net import build_resolve_fqdn, is_ipv4, resolve_ipv4
from ..secrets.system import (
    delete_system_cert,
    delete_system_secret,
    reveal_system_secret,
    store_system_cert,
    store_system_secret,
)
from ..settings import get_settings

_log = structlog.get_logger(__name__)

# Tâches de fond de ce module (resync des collecteurs…) : référencées pour ne pas
# être ramassées par le GC avant d'avoir fini (asyncio ne retient pas les tasks).
_BG_TASKS: set[asyncio.Task[None]] = set()
router = APIRouter(tags=["admin"])

# user@host : user alphanum+_- (max 32), host alphanum+._- (max 253) — aucun apostrophe
_ADDRESS_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$")


# ─── DTOs ────────────────────────────────────────────────────────────────────


class HostCreateRequest(BaseModel):
    """DTO d'entrée pour add/update host — accepte les valeurs brutes de secrets."""

    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    ci_password: str = ""  # valeur brute, stockée dans harpo au CREATE/UPDATE
    # Cert client mTLS (docker-tls) : slug d'une entrée tls-* du gestionnaire de
    # certificats. None = préservé à l'update, "" = dissocier (répertoire partagé).
    docker_cert_slug: str | None = None
    # Clé SSH (ssh) : slug d'une entrée ssh-* du gestionnaire de certificats à
    # utiliser pour la connexion. La clé publique doit déjà être autorisée sur
    # l'hôte (alternative au bootstrap). None/"" = ne rien changer (host_cert_slug
    # préservé, posé par bootstrap).
    ssh_cert_slug: str | None = None
    # None = défaut à la création ("workspaces"), valeur existante préservée à l'update.
    # ressources (spec 33) : service partagé permanent, sans workspace propriétaire.
    usage: Literal["workspaces", "tests", "portail", "ressources", "autres"] | None = None
    # Capacité d'accueil de la MACHINE. Champ ABSENT = valeur préservée ; champ
    # présent à `null` = remis à « non renseigné ». On distingue les deux par
    # `model_fields_set` : sans ça, un update partiel effacerait la capacité, et
    # une machine sans capacité connue sort du pool.
    capacity_workspaces: int | None = Field(default=None, ge=0)
    # Ouverture au pool mutualisé. None = préservé à l'update, faux à la création.
    accepts_mutualise: bool | None = None

    @field_validator("docker_cert_slug", "ssh_cert_slug")
    @classmethod
    def validate_cert_slug(cls, v: str | None) -> str | None:
        # Même format que les slugs du gestionnaire de certificats (routes/certificates.py).
        if v and not re.fullmatch(r"^[a-z0-9][a-z0-9_-]{0,62}$", v):
            raise ValueError("cert slug: lowercase alphanum + tirets/underscores, 1-63 chars")
        return v


class BootstrapSshRequest(BaseModel):
    address: str  # user@host — ex: debian@192.168.10.179
    proxmox_node: str = ""  # optionnel si host.proxmox_node est déjà connu


# ─── Config ──────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_admin_config(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    cfg = load_global()
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_admin_config(
    updates: dict[str, object], user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    cfg = load_global()
    merged: dict[str, object] = cfg.model_dump(mode="json")
    merged.update(updates)
    try:
        new_cfg = GlobalConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await save_global_db(new_cfg, conn)
    set_cached_global(new_cfg)  # après commit réussi seulement (bug 034)
    _log.info("global_config_updated", by=user.login)
    return new_cfg.model_dump(mode="json")


# ─── Configuration OIDC ──────────────────────────────────────────────────────


class OidcUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    client_id: str
    client_secret: str = ""  # vide = conserver le secret existant
    allow_local_auth: bool = True


@router.get("/oidc")
async def get_admin_oidc(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    """Config OIDC sans la valeur du secret (seulement sa présence).

    Expose aussi le redirect_uri attendu par le portail : c'est la valeur exacte à
    déclarer dans le client Keycloak (Valid redirect URIs).
    """
    oidc = load_global().auth.oidc
    return {
        "issuer": oidc.issuer,
        "client_id": oidc.client_id,
        "has_secret": bool(oidc.client_secret),
        "redirect_uri": get_settings().oidc_redirect_uri,
        "allow_local_auth": oidc.allow_local_auth,
    }


@router.put("/oidc")
async def put_admin_oidc(
    body: OidcUpdateRequest, user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    """Met à jour issuer/client_id/client_secret ; secret vide = conservé.

    Les autres réglages OIDC (scopes, claims, rôles) sont préservés.
    """
    cfg = load_global()
    existing = cfg.auth.oidc
    new_secret = body.client_secret or existing.client_secret
    new_oidc = existing.model_copy(
        update={
            "issuer": body.issuer,
            "client_id": body.client_id,
            "client_secret": new_secret,
            "allow_local_auth": body.allow_local_auth,
        }
    )
    cfg.auth = cfg.auth.model_copy(update={"oidc": new_oidc})

    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)
    _log.info("oidc_config_updated", by=user.login, issuer=body.issuer)
    return {
        "issuer": new_oidc.issuer,
        "client_id": new_oidc.client_id,
        "has_secret": bool(new_oidc.client_secret),
        "allow_local_auth": new_oidc.allow_local_auth,
    }


# ─── Configuration de la chaîne de logs centralisés (spec 30 §2) ────────────
# enabled/loki_push_url/loki_query_url/grafana_url/module/push_token : le bloc
# qui pilote à la fois le bouton "Logs" (GET /me/logs-config), la primitive MCP
# logs_query et les variables injectées aux collecteurs Alloy déployés.


class LogsConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    loki_push_url: str = ""
    loki_query_url: str = ""
    # TSDB des metriques machine (endpoint remote_write). Optionnelle : la
    # chaine des logs vit sans, et inversement.
    metrics_push_url: str = ""
    grafana_url: str = ""
    module: str = "devpod"
    push_token: str = ""  # vide = conserve le token existant (littéral ou ${vault://...})


def _logs_config_out(cfg: GlobalConfig) -> dict[str, object]:
    return {
        "enabled": cfg.logs.enabled,
        "loki_push_url": cfg.logs.loki_push_url or "",
        "loki_query_url": cfg.logs.loki_query_url or "",
        "metrics_push_url": cfg.logs.metrics_push_url or "",
        "grafana_url": cfg.logs.grafana_url or "",
        "module": cfg.logs.module,
        "has_push_token": bool(cfg.logs.push_token),
    }


@router.get("/logs-config")
async def get_admin_logs_config(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    return _logs_config_out(load_global())


@router.put("/logs-config")
async def put_admin_logs_config(
    body: LogsConfigUpdateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Active/configure la chaîne de logs. enabled=true exige les deux URLs Loki —
    sans elles ni les collecteurs (push) ni logs_query (query) n'auraient de cible.

    N'affecte pas le catalogue MCP des backends existants (logs_query n'y apparaît
    qu'après un redémarrage du portail ou un clic sur "Refresh tools" par backend).
    """
    if body.enabled and (not body.loki_push_url.strip() or not body.loki_query_url.strip()):
        raise HTTPException(
            status_code=422,
            detail="loki_push_url et loki_query_url sont requis pour activer les logs",
        )
    cfg = load_global()
    new_token = body.push_token.strip() or cfg.logs.push_token
    cfg.logs = cfg.logs.model_copy(
        update={
            "enabled": body.enabled,
            "loki_push_url": body.loki_push_url.strip() or None,
            "loki_query_url": body.loki_query_url.strip() or None,
            "metrics_push_url": body.metrics_push_url.strip() or None,
            "grafana_url": body.grafana_url.strip() or None,
            "module": body.module.strip() or "devpod",
            "push_token": new_token,
        }
    )
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    _log.info("logs_config_updated", by=user.login, enabled=body.enabled)
    # Réaligne les collecteurs Alloy déjà déployés (leur .env LOKI_URL est figé au
    # déploiement — sans resync ils pousseraient vers l'ancienne cible à jamais).
    from ..compose.service import resync_collector_deployments
    from ..db.engine import _get_engine

    async def _resync_bg() -> None:
        try:
            async with _get_engine().begin() as bg_conn:
                await resync_collector_deployments(bg_conn)
        except Exception:
            _log.warning("collector_resync_bg_failed", exc_info=True)

    task = asyncio.create_task(_resync_bg())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return _logs_config_out(cfg)


# ─── Bastion SSH → Termix ───────────────────────────────────────────────────
# Config éditable via l'IHM (plus d'.env). `enabled` démarre/arrête le sshd bastion
# à chaud ; api_url + host + role activent le provisioning Termix au cycle de vie ws.


class BastionConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    api_url: str = ""
    host: str = ""
    port: int = 2222
    role: str = ""
    apikey_secret: str = "termix-apikey"


def _bastion_config_out(cfg: GlobalConfig) -> dict[str, object]:
    b = cfg.bastion
    return {
        "enabled": b.enabled,
        "api_url": b.api_url,
        "host": b.host,
        "port": b.port,
        "role": b.role,
        "apikey_secret": b.apikey_secret,
    }


@router.get("/bastion-config")
async def get_admin_bastion_config(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    return _bastion_config_out(load_global())


@router.put("/bastion-config")
async def put_admin_bastion_config(
    body: BastionConfigUpdateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Édite la config bastion et applique le toggle sshd À CHAUD (démarrage/arrêt)."""
    cfg = load_global()
    cfg.bastion = cfg.bastion.model_copy(
        update={
            "enabled": body.enabled,
            "api_url": body.api_url.strip(),
            "host": body.host.strip(),
            "port": body.port,
            "role": body.role.strip(),
            "apikey_secret": body.apikey_secret.strip() or "termix-apikey",
        }
    )
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    from ..bastion.runtime import apply as apply_bastion

    apply_bastion(cfg.bastion.enabled)
    _log.info("bastion_config_updated", by=user.login, enabled=body.enabled)
    return _bastion_config_out(cfg)


# ─── Producteur d'events workflow (relais egress signé HMAC) ────────────────
# enabled + workflow_base_url + source_id + liste blanche `events` + secret HMAC
# (stocké comme secret système, jamais renvoyé). L'écriture reconcilie l'abonnement
# du bus à chaud (le toggle et la liste blanche prennent effet sans redémarrage).

_EVENTS_HMAC_LABEL = "Workflow events HMAC"


class EventsProducerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    workflow_base_url: str = ""
    source_id: str = ""
    source_uri: str = "urn:yoops:devpod"
    events: list[str] = Field(default_factory=list)
    secret: str = ""  # vide = conserve le secret existant (jamais renvoyé)


async def _system_secret_exists(slug: str, conn: AsyncConnection) -> bool:
    try:
        await reveal_system_secret(slug, conn)
        return True
    except KeyError:
        return False


def _events_producer_out(cfg: GlobalConfig, *, has_secret: bool) -> dict[str, object]:
    ep = cfg.events_producer
    base = cfg.server.external_url.rstrip("/") if cfg.server.external_url else ""
    return {
        "enabled": ep.enabled,
        "workflow_base_url": ep.workflow_base_url,
        "source_id": ep.source_id,
        "source_uri": ep.source_uri,
        "events": ep.events,
        "available_events": sorted(EVENT_TYPES),
        "has_secret": has_secret,
        # URL publique du catalogue d'events à enregistrer côté Workflow (source
        # « Discovery ») — c'est de cet enregistrement que Workflow renvoie le source_id.
        "discovery_url": f"{base}/schemas",
    }


@router.get("/events-producer")
async def get_admin_events_producer(
    user: UserInfo = Depends(require_admin), conn: AsyncConnection = Depends(get_conn)
) -> dict[str, object]:
    cfg = load_global()
    has_secret = await _system_secret_exists(cfg.events_producer.secret_slug, conn)
    return _events_producer_out(cfg, has_secret=has_secret)


@router.put("/events-producer")
async def put_admin_events_producer(
    body: EventsProducerUpdateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Configure le relais d'events vers le workflow ; reconcilie l'abonnement à chaud.

    Activer exige le contrat complet (URL, source_id, ≥1 event, secret présent) —
    sinon on activerait un relais qui ne pourrait rien livrer.
    """
    unknown = sorted(set(body.events) - EVENT_TYPES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"types d'events inconnus: {unknown}")

    cfg = load_global()
    slug = cfg.events_producer.secret_slug
    if body.secret.strip():
        await store_system_secret(slug, _EVENTS_HMAC_LABEL, body.secret.strip(), "local", "", conn)
    has_secret = bool(body.secret.strip()) or await _system_secret_exists(slug, conn)

    if body.enabled:
        missing = [
            name
            for name, ok in (
                ("workflow_base_url", bool(body.workflow_base_url.strip())),
                ("source_id", bool(body.source_id.strip())),
                ("events", bool(body.events)),
                ("secret", has_secret),
            )
            if not ok
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"activation impossible, champs requis manquants: {missing}",
            )

    cfg.events_producer = cfg.events_producer.model_copy(
        update={
            "enabled": body.enabled,
            "workflow_base_url": body.workflow_base_url.strip(),
            "source_id": body.source_id.strip(),
            "source_uri": body.source_uri.strip() or "urn:yoops:devpod",
            "events": body.events,
        }
    )
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    reconcile_workflow_producer()  # prise d'effet à chaud (abonnement/désabonnement)
    _log.info(
        "events_producer_config_updated",
        by=user.login,
        enabled=body.enabled,
        events=len(body.events),
    )
    return _events_producer_out(cfg, has_secret=has_secret)


def _require_producer_target(cfg_ep: Any) -> None:
    if not cfg_ep.workflow_base_url.strip() or not cfg_ep.source_id.strip():
        raise HTTPException(status_code=422, detail="URL Workflow et Source ID requis")


@router.post("/events-producer/test-connection")
async def test_events_producer_connection(
    user: UserInfo = Depends(require_admin), conn: AsyncConnection = Depends(get_conn)
) -> dict[str, object]:
    """Envoie un event de test **synchrone** et retourne le verdict de connexion.

    Valide en un geste : config complète, joignabilité du workflow, et signature
    HMAC (202). Ne passe pas par l'outbox — feedback immédiat. Utilise la config
    enregistrée (le secret vient du store) : enregistrer d'abord.
    """
    cfg = load_global().events_producer
    _require_producer_target(cfg)
    try:
        secret = await reveal_system_secret(cfg.secret_slug, conn)
    except KeyError:
        raise HTTPException(
            status_code=422, detail="secret HMAC absent — enregistrez-le d'abord"
        ) from None
    envelope = build_test_envelope(cfg.source_uri)
    raw = serialize_envelope(envelope)
    signature = compute_signature(secret.encode(), raw)
    try:
        status = await post_event(cfg.workflow_base_url, cfg.source_id, raw, signature)
    except httpx.HTTPError as exc:
        _log.warning("events_producer_test_failed", by=user.login, exc_type=type(exc).__name__)
        return {"ok": False, "event_code": envelope["_eventCode"], "error": type(exc).__name__}
    return {"ok": status == 202, "status_code": status, "event_code": envelope["_eventCode"]}


@router.post("/events-producer/send-test-event")
async def send_events_producer_test_event(
    user: UserInfo = Depends(require_admin), conn: AsyncConnection = Depends(get_conn)
) -> dict[str, object]:
    """Met en file (outbox) un event de test normalisé `{appli}.testevent.v1`.

    Emprunte le **vrai chemin asynchrone** : le worker le livrera si le relais est
    activé. Sert à valider le pipeline de bout en bout (et le déclenchement de règles).
    """
    cfg = load_global().events_producer
    _require_producer_target(cfg)
    envelope = build_test_envelope(cfg.source_uri)
    raw = serialize_envelope(envelope)
    await outbox_enqueue(
        conn,
        event_id=envelope["_eventId"],
        event_code=envelope["_eventCode"],
        raw_body=raw.decode(),
    )
    _log.info("events_producer_test_event_queued", by=user.login, event_code=envelope["_eventCode"])
    return {
        "queued": True,
        "event_id": envelope["_eventId"],
        "event_code": envelope["_eventCode"],
    }


# ─── Configuration OIDC de Grafana (SSO Keycloak du login Grafana lui-même) ───
# Distinct de /oidc (le portail) et de logs.push_token (l'auth des collecteurs
# Alloy→Loki). Auth/token/userinfo dérivées de auth.oidc.issuer : même realm
# Keycloak, un seul champ à saisir (le client secret Grafana).


def _keycloak_endpoints(issuer: str) -> tuple[str, str, str]:
    base = issuer.rstrip("/")
    return (
        f"{base}/protocol/openid-connect/auth",
        f"{base}/protocol/openid-connect/token",
        f"{base}/protocol/openid-connect/userinfo",
    )


class GrafanaOidcUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = "agflow-grafana"
    client_secret: str = ""  # vide = conserver le secret existant


@router.get("/grafana-oidc")
async def get_admin_grafana_oidc(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    """Config SSO Grafana : URLs Keycloak dérivées, secret jamais ré-exposé."""
    cfg = load_global()
    auth_url = token_url = userinfo_url = None
    if cfg.auth.oidc.issuer:
        auth_url, token_url, userinfo_url = _keycloak_endpoints(cfg.auth.oidc.issuer)
    redirect_uri = (
        f"{cfg.logs.grafana_url.rstrip('/')}/login/generic_oauth" if cfg.logs.grafana_url else None
    )
    return {
        "client_id": cfg.logs.grafana_oauth_client_id,
        "has_secret": bool(cfg.logs.grafana_oauth_client_secret),
        "auth_url": auth_url,
        "token_url": token_url,
        "userinfo_url": userinfo_url,
        "redirect_uri": redirect_uri,
        "grafana_url": cfg.logs.grafana_url,
    }


@router.put("/grafana-oidc")
async def put_admin_grafana_oidc(
    body: GrafanaOidcUpdateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Enregistre client_id/secret Grafana ; secret vide = conservé.

    Écrit aussi GF_OAUTH_* dans /data/.env (env_file de Grafana) — un
    redémarrage du conteneur Grafana reste nécessaire pour que ça s'applique
    (Grafana ne recharge pas sa config OAuth à chaud).
    """
    cfg = load_global()
    if not cfg.auth.oidc.issuer:
        raise HTTPException(
            status_code=422,
            detail="L'issuer OIDC du portail doit être configuré avant le SSO Grafana",
        )
    new_secret = body.client_secret or cfg.logs.grafana_oauth_client_secret
    cfg.logs = cfg.logs.model_copy(
        update={
            "grafana_oauth_client_id": body.client_id,
            "grafana_oauth_client_secret": new_secret,
        }
    )
    await save_global_db(cfg, conn)
    set_cached_global(cfg)

    auth_url, token_url, userinfo_url = _keycloak_endpoints(cfg.auth.oidc.issuer)
    env_updates = {
        "GF_OAUTH_CLIENT_ID": body.client_id,
        "GF_OAUTH_AUTH_URL": auth_url,
        "GF_OAUTH_TOKEN_URL": token_url,
        "GF_OAUTH_API_URL": userinfo_url,
    }
    if body.client_secret:
        env_updates["GF_OAUTH_CLIENT_SECRET"] = body.client_secret
    await update_env_file(_data_root() / ".env", env_updates)

    _log.info("grafana_oauth_config_updated", by=user.login, client_id=body.client_id)
    return {"client_id": body.client_id, "has_secret": bool(new_secret)}


# ─── Domaine local (résolution DNS des VM de test DHCP) ─────────────────────


class LocalDomainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_domain: str = ""


@router.get("/local-domain")
async def get_local_domain(user: UserInfo = Depends(require_admin)) -> dict[str, str]:
    return {"local_domain": load_global().server.local_domain}


@router.put("/local-domain")
async def put_local_domain(
    body: LocalDomainRequest, user: UserInfo = Depends(require_admin)
) -> dict[str, str]:
    """Domaine DNS local ajouté au nom d'une VM de test pour re-résoudre son IP DHCP."""
    cfg = load_global()
    cfg.server = cfg.server.model_copy(update={"local_domain": body.local_domain.strip()})
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)
    _log.info("local_domain_updated", by=user.login, local_domain=cfg.server.local_domain)
    return {"local_domain": cfg.server.local_domain}


class NetworkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_domain: str = ""
    external_url: str = ""
    workspace_host: str = ""
    dev_mode: bool = False
    vs_proxy_domain: str = ""
    cookie_domain: str = ""


@router.get("/network")
async def get_network(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    s = load_global().server
    return {
        "base_domain": s.base_domain,
        "external_url": s.external_url,
        "workspace_host": s.workspace_host,
        "dev_mode": s.dev_mode,
        "vs_proxy_domain": s.vs_proxy_domain,
        "cookie_domain": s.cookie_domain,
    }


@router.put("/network")
async def put_network(
    body: NetworkRequest, user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    """Config réseau : domaine de base, URL externe, hôte direct des workspaces.

    base_domain renseigné → exposition des workspaces par sous-domaine Caddy.
    dev_mode=True → URL directe IP:port (pas de route Caddy, pour accès local sans tunnel).
    """
    try:
        clean = validate_network(
            body.base_domain,
            body.external_url,
            body.workspace_host,
            body.vs_proxy_domain,
            body.cookie_domain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cfg = load_global()
    cfg.server = cfg.server.model_copy(update={**clean, "dev_mode": body.dev_mode})
    from ..db.engine import _get_engine
    from ..routes.workspace_ops import _reset_service, re_expose_running_workspaces

    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)
    # Invalider le singleton DevPodService (embarque ExposureService avec dev_mode/base_domain
    # baked-in). Le prochain _get_service() le recrée depuis la DB.
    _reset_service()
    # Actualise immédiatement le domaine du cookie de session (sans redémarrage).
    from ..settings import update_cookie_domain

    update_cookie_domain(
        clean.get("cookie_domain", ""),
        clean.get("base_domain", ""),
        external_url=clean.get("external_url", ""),
        vs_proxy_domain=clean.get("vs_proxy_domain", ""),
    )
    # Réexposer immédiatement les workspaces actifs avec la nouvelle config.
    await re_expose_running_workspaces()
    _log.info(
        "network_config_updated",
        by=user.login,
        base_domain=clean["base_domain"],
        dev_mode=body.dev_mode,
    )
    return {
        **clean,
        "dev_mode": body.dev_mode,
        "vs_proxy_domain": clean.get("vs_proxy_domain", ""),
        "cookie_domain": clean.get("cookie_domain", ""),
    }


class ResolveHostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = ""


class SessionDurationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Secondes. 0 interdit ici (l'admin doit poser une valeur explicite ; pour
    # « hériter du défaut » on ne passe simplement pas par cette route).
    session_max_age: int = Field(ge=60, le=86400)
    session_absolute_max_age: int = Field(ge=60, le=604800)

    @field_validator("session_absolute_max_age")
    @classmethod
    def _absolute_ge_idle(cls, v: int, info: Any) -> int:
        idle = info.data.get("session_max_age")
        if isinstance(idle, int) and v < idle:
            raise ValueError("le plafond absolu doit être ≥ à l'idle glissant")
        return v


@router.get("/sessions")
async def get_sessions_config(user: UserInfo = Depends(require_admin)) -> dict[str, int]:
    """Durées de session EFFECTIVES (override admin sinon défaut settings/env)."""
    from ..config.store import effective_session_absolute_max_age, effective_session_max_age

    return {
        "session_max_age": effective_session_max_age(),
        "session_absolute_max_age": effective_session_absolute_max_age(),
    }


@router.put("/sessions")
async def put_sessions_config(
    body: SessionDurationsRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, int]:
    """Écrit les durées de session (idle glissant + plafond absolu). Effet immédiat,
    sans redémarrage : le cookie relit `session_max_age` à l'émission et rbac relit
    le plafond à chaque requête."""
    cfg = load_global()
    cfg.server = cfg.server.model_copy(
        update={
            "session_max_age": body.session_max_age,
            "session_absolute_max_age": body.session_absolute_max_age,
        }
    )
    await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)
    _log.info(
        "session_durations_updated",
        by=user.login,
        session_max_age=body.session_max_age,
        session_absolute_max_age=body.session_absolute_max_age,
    )
    return {
        "session_max_age": body.session_max_age,
        "session_absolute_max_age": body.session_absolute_max_age,
    }


# ─── Défauts workspaces (enabler 59864c37) ───────────────────────────────────


class WorkspaceDefaultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Limite mémoire par défaut des conteneurs workspace (docker --memory).
    # "" = aucune limite. Appliquée à la (re)construction du conteneur.
    memory_limit: str = ""

    @field_validator("memory_limit")
    @classmethod
    def _validate_memory_limit(cls, v: str) -> str:
        from ..config.models import _validate_memory_limit

        return _validate_memory_limit(v)


@router.get("/workspace-defaults")
async def get_workspace_defaults(user: UserInfo = Depends(require_admin)) -> dict[str, str]:
    return {"memory_limit": load_global().devpod.defaults.memory_limit}


@router.put("/workspace-defaults")
async def put_workspace_defaults(
    body: WorkspaceDefaultsRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Écrit la limite mémoire par défaut. Prend effet au prochain up/recreate
    de chaque workspace (runArgs --memory dans le devcontainer généré)."""
    cfg = load_global()
    new_defaults = cfg.devpod.defaults.model_copy(update={"memory_limit": body.memory_limit})
    cfg.devpod = cfg.devpod.model_copy(update={"defaults": new_defaults})
    await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)
    _log.info("workspace_defaults_updated", by=user.login, memory_limit=body.memory_limit)
    return {"memory_limit": body.memory_limit}


@router.post("/network/resolve-workspace-host")
async def resolve_workspace_host(
    body: ResolveHostRequest, user: UserInfo = Depends(require_admin)
) -> dict[str, str]:
    """Résout l'IPv4 courante de workspace_host pour tester la config DHCP.

    IP littérale → renvoyée telle quelle. Sinon `<host>.<local_domain>` est résolu
    via le resolver du portail. 422 si vide, 502 si non résolvable.
    """
    host = body.host.strip()
    if not host:
        raise HTTPException(status_code=422, detail="host vide")
    if is_ipv4(host):
        _log.info("resolve_workspace_host_literal_ip", by=user.login, host=host)
        return {"fqdn": host, "ip": host}
    fqdn = build_resolve_fqdn(host, load_global().server.local_domain)
    _log.info("resolve_workspace_host_start", by=user.login, host=host, fqdn=fqdn)
    try:
        ip = await resolve_ipv4(fqdn)
    except OSError as exc:
        _log.warning("resolve_workspace_host_failed", by=user.login, fqdn=fqdn, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Non résolvable : {fqdn} ({exc})") from exc
    _log.info("resolve_workspace_host_done", by=user.login, fqdn=fqdn, ip=ip)
    return {"fqdn": fqdn, "ip": ip}


# ─── Hosts CRUD ──────────────────────────────────────────────────────────────


async def _materialize_docker_cert(
    login: str, session_id: str, host_name: str, slug: str, conn: AsyncConnection
) -> None:
    """Matérialise le bundle mTLS d'un host depuis le gestionnaire de certificats.

    Exige un cert tls-* IMPORTÉ (X.509, pas une paire de clés générée), avec CA,
    dont l'admin est propriétaire (le reveal de la clé passe par sa session vault).
    Toute condition non remplie = erreur explicite, jamais de bundle partiel.
    """
    row = await get_certificate(login, slug, conn)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Certificat {slug!r} introuvable")
    if not str(row["cert_type"]).startswith("tls-"):
        raise HTTPException(
            status_code=422,
            detail=f"Certificat {slug!r} : type {row['cert_type']} — un cert tls-* est requis",
        )
    if not row["is_own"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Certificat {slug!r} : appartient à {row['owner_login']} — seul un cert "
                "dont vous êtes propriétaire peut être associé (clé privée à matérialiser)"
            ),
        )
    cert_pem = str(row["public_key"] or "")
    if "-----BEGIN CERTIFICATE-----" not in cert_pem:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Certificat {slug!r} : la partie publique n'est pas un certificat X.509 "
                "(entrée générée = paire de clés) — importez un bundle cert client + clé + CA"
            ),
        )
    ca_pem = str(row["ca_pem"] or "")
    if not ca_pem:
        raise HTTPException(
            status_code=422,
            detail=f"Certificat {slug!r} : CA manquant — le mTLS docker exige ca.pem",
        )
    try:
        key_pem = await reveal_private_key(login, session_id, slug, conn)
    except VaultLocked as exc:
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    except CertNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Clé privée de {slug!r} inaccessible") from exc
    # Normalisation (CRLF/newline final d'un bundle collé) — sinon TLS/SSH le rejettent.
    await materialize_host_bundle(
        host_name,
        ca_pem=normalize_pem(ca_pem),
        cert_pem=normalize_pem(cert_pem),
        key_pem=normalize_pem(key_pem),
    )
    _log.info("host_docker_cert_associated", host=host_name, slug=slug, by=login)


async def _materialize_ssh_cert(
    login: str, session_id: str, host_name: str, slug: str, conn: AsyncConnection
) -> str:
    """Matérialise une clé SSH du gestionnaire comme cert système `host.<name>.cert`.

    Alternative au bootstrap : la clé publique choisie doit déjà être autorisée sur
    l'hôte (aucune installation distante ici). Exige un cert ssh-* dont l'admin est
    propriétaire (le reveal passe par sa session vault). Retourne le slug système.
    """
    row = await get_certificate(login, slug, conn)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Certificat {slug!r} introuvable")
    if not str(row["cert_type"]).startswith("ssh-"):
        raise HTTPException(
            status_code=422,
            detail=f"Certificat {slug!r} : type {row['cert_type']} — une clé ssh-* est requise",
        )
    if not row["is_own"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Certificat {slug!r} : appartient à {row['owner_login']} — seule une clé "
                "dont vous êtes propriétaire peut être associée (clé privée à matérialiser)"
            ),
        )
    try:
        private_pem = await reveal_private_key(login, session_id, slug, conn)
    except VaultLocked as exc:
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    except CertNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Clé privée de {slug!r} inaccessible") from exc

    system_slug = f"host.{host_name}.cert"
    await store_system_cert(
        slug=system_slug,
        label=f"SSH key — {host_name}",
        # Clé souvent collée depuis Windows (CRLF) → « error in libcrypto » côté ssh.
        private_pem=normalize_pem(private_pem),
        public_key=str(row["public_key"] or ""),
        cert_type=str(row["cert_type"]),
        storage_type="local",
        vault_identifier="",
        conn=conn,
    )
    _log.info("host_ssh_cert_associated", host=host_name, slug=slug, by=login)
    return system_slug


@router.get("/hosts")
async def list_hosts(user: UserInfo = Depends(require_admin)) -> list[dict[str, object]]:
    cfg = load_global()
    return [h.model_dump(mode="json") for h in cfg.hosts]


@router.post("/hosts", status_code=201)
async def add_host(
    body: HostCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    cfg = load_global()
    if any(h.name == body.name for h in cfg.hosts):
        raise HTTPException(status_code=409, detail=f"Host {body.name!r} already exists")

    ci_slug = ""
    if body.ci_password:
        ci_slug = f"host.{body.name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {body.name}",
            value=body.ci_password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )

    session_id = str(request.session.get("session_id", ""))
    # Clé SSH choisie dans le gestionnaire → matérialisée comme cert système du host.
    host_cert_slug = ""
    if body.type == "ssh" and body.ssh_cert_slug:
        host_cert_slug = await _materialize_ssh_cert(
            user.login, session_id, body.name, body.ssh_cert_slug, conn
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug=host_cert_slug,
        docker_cert_slug=body.docker_cert_slug or "",
        storage_type="local",
        vault_identifier="",
        usage=body.usage or "workspaces",
        capacity_workspaces=body.capacity_workspaces,
        accepts_mutualise=bool(body.accepts_mutualise),
    )
    # Bundle mTLS matérialisé AVANT persistance : une association invalide
    # (cert sans CA, vault verrouillé…) ne doit pas laisser un host à moitié câblé.
    if host.type == "docker-tls" and host.docker_cert_slug:
        await _materialize_docker_cert(
            user.login, session_id, host.name, host.docker_cert_slug, conn
        )
    cfg.hosts.append(host)
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    _log.info("host_added", name=body.name, by=user.login)
    # Pousse le serveur vers Termix (dossier selon usage) après commit (best-effort).
    background_tasks.add_task(bastion_servers.sync_server_host, body.name)
    return host.model_dump(mode="json")


@router.put("/hosts/{name}")
async def update_host(
    name: str,
    body: HostCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    if body.name != name:
        raise HTTPException(status_code=422, detail="Host name in body must match URL")
    cfg = load_global()
    idx = next((i for i, h in enumerate(cfg.hosts) if h.name == name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    existing = cfg.hosts[idx]
    ci_slug = existing.ci_password_secret_slug

    # Si un nouveau ci_password est fourni, remplacer dans harpo (store est idempotent)
    if body.ci_password:
        ci_slug = f"host.{name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {name}",
            value=body.ci_password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )

    session_id = str(request.session.get("session_id", ""))
    # Nouvelle clé SSH choisie → rematérialisée comme cert système ; sinon on conserve
    # host_cert_slug tel quel (posé par bootstrap ou une association précédente).
    host_cert_slug = existing.host_cert_slug
    if body.type == "ssh" and body.ssh_cert_slug:
        host_cert_slug = await _materialize_ssh_cert(
            user.login, session_id, body.name, body.ssh_cert_slug, conn
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug=host_cert_slug,
        # None = préservé (client qui n'envoie pas le champ), "" = dissocier explicitement.
        docker_cert_slug=(
            existing.docker_cert_slug if body.docker_cert_slug is None else body.docker_cert_slug
        ),
        storage_type=existing.storage_type,  # conservé (l'update ne doit rien réinitialiser)
        vault_identifier=existing.vault_identifier,  # conservé
        usage=body.usage if body.usage is not None else existing.usage,
        # Provenance conservée : elle est posée au provisionnement, pas saisie
        # par l'administrateur — et l'oublier ici l'effacerait à chaque update.
        profile_slug=existing.profile_slug,
        hypervisor=existing.hypervisor,
        # Champ absent du corps = préservé ; présent à `null` = effacé.
        capacity_workspaces=(
            body.capacity_workspaces
            if "capacity_workspaces" in body.model_fields_set
            else existing.capacity_workspaces
        ),
        accepts_mutualise=(
            existing.accepts_mutualise if body.accepts_mutualise is None else body.accepts_mutualise
        ),
    )
    # Bundle mTLS : rematérialisé uniquement si le slug CHANGE (un update sans rapport
    # ne doit pas exiger le vault déverrouillé) ; "" = dissociation → purge du bundle.
    if host.docker_cert_slug != existing.docker_cert_slug:
        if host.docker_cert_slug:
            await _materialize_docker_cert(
                user.login, session_id, host.name, host.docker_cert_slug, conn
            )
        else:
            await remove_host_bundle(host.name)
    cfg.hosts[idx] = host
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    _log.info("host_updated", name=name, by=user.login)
    # Re-pousse le serveur (ip/user/usage/clé ont pu changer → dossier/cible) après commit.
    background_tasks.add_task(bastion_servers.sync_server_host, name)
    return host.model_dump(mode="json")


@router.delete("/hosts/{name}", status_code=204)
async def delete_host(
    name: str,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    # 1. Supprimer tous les workspaces sur ce host.
    # host="" = "hôte par défaut" dans le formulaire de création. Si le host supprimé
    # est le default, ces workspaces lui appartiennent aussi.
    from sqlalchemy import or_

    host_condition = _ws_table.c.host == name
    if host_cfg.default:
        host_condition = or_(host_condition, _ws_table.c.host == "")
    rows = (
        (await conn.execute(select(_ws_table.c.login, _ws_table.c.name).where(host_condition)))
        .mappings()
        .all()
    )

    if rows:
        from .workspace_ops import _get_service

        svc = _get_service()

        async def _delete_one(login: str, ws_name: str) -> None:
            ws_id = f"{login}-{ws_name}"
            try:
                await svc.delete(login=login, ws_id=ws_id, shelve=False)
            except Exception:
                _log.warning("host_delete_ws_failed", host=name, ws_id=ws_id, exc_info=True)
            finally:
                # Toujours supprimer la config du workspace, même si devpod delete a échoué.
                # svc.delete() purge workspace_status mais jamais la table workspaces.
                await conn.execute(
                    sql_delete(_ws_table)
                    .where(_ws_table.c.login == login)
                    .where(_ws_table.c.name == ws_name)
                )

        await asyncio.gather(*[_delete_one(r["login"], r["name"]) for r in rows])

    # 2. Exécuter le destroy_script de l'hyperviseur (si VM gérée par Proxmox)
    from .proxmox import _run_destroy_script

    await _run_destroy_script(cfg, host_cfg)

    # 3. Nettoyer les secrets harpo avant de retirer le host
    if host_cfg.ci_password_secret_slug:
        await delete_system_secret(host_cfg.ci_password_secret_slug, conn)
    if host_cfg.host_cert_slug:
        await delete_system_cert(host_cfg.host_cert_slug, conn)
    if host_cfg.docker_cert_slug:
        await remove_host_bundle(host_cfg.name)

    # 4. Retirer le host de la config
    cfg.hosts = [h for h in cfg.hosts if h.name != name]
    await save_global_db(cfg, conn)

    # 5. Detacher ce qui reference le host par son NOM. Sans ca, une VM de test
    #    supprimee d'ici laissait son association de workspace et ses
    #    deploiements compose derriere elle : la machine suivante a porter ce
    #    nom heritait des lignes de l'ancienne, et la suppression cote workspace
    #    echouait sur `MultipleResultsFound` — le seul chemin qui aurait permis
    #    de nettoyer.
    from ..compose.db import delete_deployments_for_node
    from ..db.test_hosts import list_test_host_message_ids, remove_test_host
    from ..messages.service import delete_message as _msg_delete

    for message_id in await list_test_host_message_ids(name, conn):
        await _msg_delete(conn, message_id)
    await remove_test_host(name, conn)
    purges = await delete_deployments_for_node(conn, name)

    set_cached_global(cfg)
    _log.info(
        "host_deleted",
        name=name,
        by=user.login,
        workspaces_deleted=len(rows),
        deployments_purged=purges,
    )
    # Retire le serveur de Termix chez tous ses destinataires après commit (best-effort).
    background_tasks.add_task(bastion_servers.deprovision_server_host, name)


@router.get("/hosts/{name}/workspaces")
async def list_host_workspaces(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """Retourne les workspaces qui tournent sur ce host, groupés par utilisateur.

    Le rattachement se fait sur le host **effectif** (`workspace_status.host_name`,
    résolu au déploiement), et non sur `workspaces.host` qui n'est que le choix de
    l'utilisateur — vide ("") quand « default » est sélectionné, donc jamais égal à
    un nom de host.
    """
    from sqlalchemy import func as _func

    ws_id_expr = _func.concat(_ws_table.c.login, "-", _ws_table.c.name)
    rows = (
        (
            await conn.execute(
                select(
                    _ws_table.c.login,
                    _ws_table.c.name,
                    _ws_status_table.c.status,
                )
                .select_from(
                    _ws_table.join(_ws_status_table, _ws_status_table.c.ws_id == ws_id_expr)
                )
                .where(_ws_status_table.c.host_name == name)
                .order_by(_ws_table.c.login, _ws_table.c.name)
            )
        )
        .mappings()
        .all()
    )

    by_login: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_login.setdefault(r["login"], []).append(
            {"name": r["name"], "status": r["status"] or "unknown"}
        )

    return [{"login": login, "workspaces": wss} for login, wss in by_login.items()]


@router.get("/hosts/{name}/test-info")
async def get_host_test_info(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str] | None:
    """Retourne le workspace propriétaire d'un host de test, ou null si pas un host de test."""
    from ..db.test_hosts import host_full_info

    info = await host_full_info(name, conn)
    if info is None:
        return None
    login, workspace_name, alias = info
    return {"owner_login": login, "workspace_name": workspace_name, "alias": alias}


@router.get("/hosts/{name}/deployments")
async def list_host_deployments(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """Déploiements compose actifs sur ce nœud."""
    from ..compose.db import get_template, list_deployments_for_node
    from ..compose.models import ComposeTemplate

    deps = await list_deployments_for_node(conn, name)
    result: list[dict[str, object]] = []
    for dep in deps:
        tpl: ComposeTemplate | None = await get_template(conn, dep.template_id)
        result.append(
            {
                "id": dep.id,
                "status": dep.status,
                "template_id": dep.template_id,
                "template_name": tpl.name if tpl else dep.template_id,
                "template_version": dep.template_version,
                "host_ports": dep.host_ports,
                "last_error": dep.last_error,
                "created_at": dep.created_at.isoformat() if dep.created_at else None,
            }
        )
    return result


# ─── Bootstrap SSH ───────────────────────────────────────────────────────────


@router.post("/hosts/{name}/bootstrap-ssh")
async def bootstrap_host_ssh(
    name: str,
    body: BootstrapSshRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Configure un host SSH : génère paire ed25519, stocke dans harpo, injecte la pubkey via PVE.

    Flux : portail → SSH PVE → SSH VM → ~/.ssh/authorized_keys
    Idempotent : l'injection n'ajoute la clé que si elle n'est pas déjà présente.
    La clé privée ne sort JAMAIS de cette route.
    """
    log = _log.bind(host=name, address=body.address, by=user.login)
    log.info("bootstrap_ssh_start")

    if not _ADDRESS_RE.fullmatch(body.address):
        log.warning("bootstrap_ssh_invalid_address")
        raise HTTPException(status_code=422, detail="address invalide (attendu : user@host)")

    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        log.warning("bootstrap_ssh_host_not_found")
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")
    if host.type != "ssh":
        log.warning("bootstrap_ssh_wrong_type", host_type=host.type)
        raise HTTPException(
            status_code=422,
            detail="bootstrap-ssh disponible pour les hosts de type ssh uniquement",
        )

    # Résolution du nœud PVE : corps de la requête → host.proxmox_node → 422
    resolved_pve = body.proxmox_node or host.proxmox_node
    if not resolved_pve:
        log.warning("bootstrap_ssh_no_proxmox_node")
        raise HTTPException(
            status_code=422,
            detail="proxmox_node requis (non mémorisé sur le host)",
        )
    pve_node = next((n for n in cfg.hypervisors if n.name == resolved_pve), None)
    if pve_node is None:
        log.warning("bootstrap_ssh_pve_not_found", pve=resolved_pve)
        raise HTTPException(status_code=404, detail=f"Nœud Proxmox {resolved_pve!r} introuvable")

    log.info("bootstrap_ssh_pve_resolved", pve=resolved_pve, pve_address=pve_node.address)

    # Génère une paire ed25519 en mémoire (jamais sur disque)
    try:
        private_key_obj = Ed25519PrivateKey.generate()
        private_pem = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_key = (
            private_key_obj.public_key()
            .public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH,
            )
            .decode()
            .strip()
        )
    except Exception:
        log.exception("bootstrap_ssh_keygen_failed")
        raise

    log.info("bootstrap_ssh_keygen_ok")

    # La clé SSH du host est un secret d'infrastructure : toujours local (PORTAL_VAULT_KEK).
    cert_slug = f"host.{name}.cert"
    try:
        await store_system_cert(
            slug=cert_slug,
            label=f"SSH key — {name}",
            # Clé souvent collée depuis Windows (CRLF) → « error in libcrypto » côté ssh.
            private_pem=normalize_pem(private_pem),
            public_key=public_key,
            cert_type="ssh-ed25519",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    except Exception:
        log.exception("bootstrap_ssh_store_cert_failed", slug=cert_slug)
        raise

    log.info("bootstrap_ssh_cert_stored", slug=cert_slug)

    # Injecte la pubkey dans la VM via un saut PVE
    inner_cmd = (
        "mkdir -p ~/.ssh && "
        "chmod 700 ~/.ssh && "
        f"grep -qxF {shlex.quote(public_key)} ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo {shlex.quote(public_key)} >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )
    inject_script = (
        "set -euo pipefail\n"
        f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "
        f"-o ConnectTimeout=15 {shlex.quote(body.address)} {shlex.quote(inner_cmd)}\n"
    )

    from .proxmox import _ssh_opts

    ssh_cmd = ["ssh", *_ssh_opts(pve_node), f"{pve_node.ssh_user}@{pve_node.address}", "bash -s"]
    log.info("bootstrap_ssh_inject_start", ssh_cmd=ssh_cmd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=inject_script.encode()), timeout=30.0
        )
    except TimeoutError:
        proc.kill()
        log.error("bootstrap_ssh_inject_timeout")
        raise HTTPException(status_code=504, detail="Injection de clé SSH : timeout") from None
    except Exception:
        log.exception("bootstrap_ssh_inject_exec_failed")
        raise

    stderr_str = stderr.decode("utf-8", errors="replace").strip()
    log.info(
        "bootstrap_ssh_inject_done",
        returncode=proc.returncode,
        stderr=stderr_str or "(empty)",
    )

    if proc.returncode != 0:
        raise HTTPException(
            status_code=502, detail=f"Injection de clé SSH échouée : {stderr_str or '(no stderr)'}"
        )

    # Met à jour address, proxmox_node et host_cert_slug dans le config
    idx = next(i for i, h in enumerate(cfg.hosts) if h.name == name)
    cfg.hosts[idx] = cfg.hosts[idx].model_copy(
        update={
            "address": body.address,
            "proxmox_node": resolved_pve,
            "host_cert_slug": cert_slug,
        }
    )
    try:
        await save_global_db(cfg, conn)
    except Exception:
        log.exception("bootstrap_ssh_save_failed")
        raise
    set_cached_global(cfg)

    log.info("bootstrap_ssh_done")
    return {"public_key": public_key, "address": body.address, "host_cert_slug": cert_slug}


# ─── Cert ────────────────────────────────────────────────────────────────────


@router.get("/hosts/{name}/cert")
async def get_host_cert(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Retourne la clé publique (SSH) ou les fichiers TLS (docker-tls) du host.

    SSH  : lit depuis harpo_certificates — retourne public_key + cert_type.
    TLS  : lit ca.pem + cert.pem depuis cfg.devpod.client_cert_path.
    Seuls les fichiers publics sont exposés (jamais la clé privée).
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    if host.type == "ssh":
        if not host.host_cert_slug:
            raise HTTPException(
                status_code=404,
                detail="Clé SSH non configurée (lancez bootstrap-ssh)",
            )
        row = (
            (
                await conn.execute(
                    select(harpo_certificates)
                    .where(harpo_certificates.c.owner_login == "__system__")
                    .where(harpo_certificates.c.slug == host.host_cert_slug)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Cert introuvable en base")
        return {"public_key": str(row["public_key"]), "cert_type": str(row["cert_type"])}

    # docker-tls : bundle par host si un cert du gestionnaire est associé,
    # sinon répertoire de certs partagé du portail.
    if host.docker_cert_slug:
        raw_path = str(host_bundle_dir(host.name))
    else:
        raw_path = cfg.devpod.client_cert_path
    if not raw_path:
        raise HTTPException(status_code=422, detail="client_cert_path non configuré")

    from pathlib import Path

    cert_dir = Path(raw_path).resolve()
    data_root = _data_root().resolve()
    if not cert_dir.is_relative_to(data_root):
        raise HTTPException(status_code=403, detail="Chemin cert non autorisé (hors /data)")

    result: dict[str, str] = {}
    for cert_name in ("ca.pem", "cert.pem"):
        cert_file = cert_dir / cert_name
        if cert_file.exists():
            result[cert_name] = cert_file.read_text(encoding="utf-8")

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun fichier de certificat trouvé dans {raw_path}",
        )
    return result


# ─── SSH helper (conservé pour les WebSocket SSH proxy) ─────────────────────


async def _run_script_on_pve(node: Hypervisor, script: str, timeout: float = 30.0) -> str:
    """Exécute un script bash sur un nœud PVE via SSH stdin ; lève RuntimeError si erreur."""
    from .proxmox import _ssh_opts

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
        "bash -s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=script.encode()), timeout=timeout
        )
    except TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"SSH script exited {proc.returncode}: {msg or '(no stderr)'}")
    return stdout.decode("utf-8", errors="replace")
