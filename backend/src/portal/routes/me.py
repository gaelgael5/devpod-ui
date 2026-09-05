from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..billing.allocation import QuotaDepasse
from ..certificates import service as cert_svc
from ..config.models import GitCredential, ProfileRef, SourceSpec, UserConfig, WorkspaceSpec
from ..config.store import (
    load_global,
    load_user,
    safe_user_path,
    save_user,
    user_config_lock,
)
from ..db.engine import get_conn
from ..db.tables import users
from ..db.user_config import save_user_db
from ..db.workspace_quota import verifier_quota_creation, verrouiller_creation
from ..devpod.git import probe_git_credential, run_git_ls_remote
from ..secrets import service as secret_svc

_CRED_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$")
# Validation email « pragmatique » : local@domaine.tld, sans espace ni @ superflu.
# On ne vise pas la conformité RFC 5322 complète (inexploitable), juste un garde-fou
# contre les saisies manifestement invalides. Chaîne vide autorisée = efface l'email.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Identité OBO : charset sûr (part dans un en-tête HTTP → pas de CR/LF ni contrôle).
# Couvre les UUID et identifiants usuels des services. Vide efface (retombe sur le sub).
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

# Champs de UserConfig modifiables par l'utilisateur via PUT /me/config (bug 008).
# secret_ns/version/workspaces/git_credentials/harpocrate sont exclus : ils ont leurs
# propres invariants (isolation, cohérence FK, endpoints CRUD dédiés) et ne doivent
# jamais transiter par ce merge générique.
_ALLOWED_CONFIG_UPDATE_FIELDS = {"defaults", "culture"}

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["me"])


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


class _ProfilePatch(BaseModel):
    # Patch partiel : seuls les champs fournis sont mis à jour. Le login n'y figure
    # pas — c'est la clé d'identité (PK users + dossier /data/users/<login>), immuable.
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    email: str | None = None
    # Identité propagée aux services MCP (on-behalf-of). "" = effacer (retombe sur le sub).
    identity: str | None = None


async def _read_profile(conn: AsyncConnection, login: str) -> dict[str, object]:
    from sqlalchemy import select

    row = (
        (
            await conn.execute(
                select(
                    users.c.login,
                    users.c.email,
                    users.c.display_name,
                    users.c.identity,
                ).where(users.c.login == login)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return {"login": login, "email": "", "display_name": "", "identity": ""}
    return {
        "login": row["login"],
        "email": row["email"],
        "display_name": row["display_name"],
        # Identité propagée aux services MCP (GUID). Vide = rien propagé (guid-only).
        "identity": row["identity"] or "",
    }


@router.get("/profile")
async def get_profile(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    return await _read_profile(conn, user.login)


@router.get("/token-claims")
async def get_token_claims(
    request: Request,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Claims essentiels du jeton OIDC de la session (affichage/copie sur la page profil).

    Ne renvoie JAMAIS le jeton brut ni l'access_token : uniquement le sous-ensemble
    curé persisté au login (`token_claims`). Le `sub` (ancre d'identité) est garanti
    même sur une session antérieure à cette fonctionnalité.
    """
    claims = dict(request.session.get("token_claims") or {})
    sub = (request.session.get("user") or {}).get("sub")
    if sub and not claims.get("sub"):
        claims["sub"] = str(sub)
    return {"claims": claims}


@router.patch("/profile")
async def patch_profile(
    body: _ProfilePatch,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    from sqlalchemy import update

    values: dict[str, str | None] = {}

    if body.display_name is not None:
        display_name = body.display_name.strip()
        if len(display_name) > 80:
            raise HTTPException(status_code=422, detail="display_name must be ≤ 80 characters")
        values["display_name"] = display_name

    if body.email is not None:
        email = body.email.strip()
        if len(email) > 254:
            raise HTTPException(status_code=422, detail="email must be ≤ 254 characters")
        if email and not _EMAIL_RE.fullmatch(email):
            raise HTTPException(status_code=422, detail="email is not a valid address")
        values["email"] = email

    if body.identity is not None:
        ident = body.identity.strip()
        if ident:
            # Charset restreint : cette valeur part telle quelle dans un en-tête HTTP
            # (x-portal-actor) → interdire tout ce qui permettrait une injection d'en-tête.
            if len(ident) > 200 or not _IDENTITY_RE.fullmatch(ident):
                raise HTTPException(
                    status_code=422,
                    detail="identity: 1 à 200 caractères parmi [A-Za-z0-9._:-]",
                )
            identity_value: str | None = ident
        else:
            identity_value = None  # vide = effacer → retombe sur le sub
        values["identity"] = identity_value

    if not values:
        raise HTTPException(status_code=422, detail="no profile field to update")

    try:
        await conn.execute(update(users).where(users.c.login == user.login).values(**values))
    except IntegrityError as exc:
        # Seule contrainte unique touchée ici : uq_users_identity.
        raise HTTPException(
            status_code=409, detail="identity déjà utilisée par un autre compte"
        ) from exc
    _log.info("user_profile_updated", login=user.login, fields=sorted(values))
    # On relit la ligne pour renvoyer le profil complet (login, email, display_name) :
    # le frontend rafraîchit son cache avec cette réponse, elle doit être cohérente.
    return await _read_profile(conn, user.login)


@router.get("")
async def get_current_user(user: UserInfo = Depends(require_user)) -> dict[str, object]:
    from ..settings import get_settings

    # is_admin calculé côté serveur : le NOM du rôle admin (oidc_admin_role) est
    # une config de déploiement — le frontend ne doit pas le connaître (bug :
    # un `roles.includes('admin')` codé en dur cassait l'UI admin dès que le
    # realm utilisait un autre nom, ex. yoops-admin).
    return {
        "login": user.login,
        "roles": user.roles,
        "is_admin": get_settings().oidc_admin_role in user.roles,
    }


@router.get("/termix-instances")
async def get_my_termix_instances(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """Serveurs Termix effectifs de l'utilisateur (lecture seule, spec 18 T4b).

    Résolus (rattachés explicitement, sinon défaut). Champs publics uniquement —
    jamais l'apikey.
    """
    from ..db import user_termix_instance as uti

    resolved = await uti.resolve_instances_for_user(conn, user.login)
    return [{"id": i["id"], "name": i["name"], "url": i["url"]} for i in resolved]


@router.get("/logs-config")
async def get_logs_config(_user: UserInfo = Depends(require_user)) -> dict[str, object]:
    """Expose les paramètres Grafana nécessaires au frontend (pas de secrets)."""
    cfg = load_global()
    return {"enabled": cfg.logs.enabled, "grafana_url": cfg.logs.grafana_url}


@router.get("/config")
async def get_config(user: UserInfo = Depends(require_user)) -> dict[str, object]:
    cfg = await load_user(user.login)
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_config(
    updates: dict[str, object], user: UserInfo = Depends(require_user)
) -> dict[str, object]:
    # Allowlist stricte : secret_ns/version/workspaces/git_credentials/harpocrate ont
    # leurs propres invariants (isolation, cohérence, endpoints CRUD dédiés) — jamais
    # via ce merge générique, sous peine de laisser un client réécrire son secret_ns.
    disallowed = set(updates) - _ALLOWED_CONFIG_UPDATE_FIELDS
    if disallowed:
        raise HTTPException(
            status_code=422,
            detail=f"Champs non modifiables via cet endpoint : {sorted(disallowed)}",
        )
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        merged = cfg.model_dump(mode="json")
        merged.update(updates)
        try:
            new_cfg = UserConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await save_user(user.login, new_cfg)
    _log.info("user_config_updated", login=user.login)
    return new_cfg.model_dump(mode="json")


def _memory_borne(host_name: str, memory_limit: str) -> str | None:
    """Valeur à laquelle la limite sera ramenée au prochain démarrage, ou None.

    Signalement du parc existant (enabler « Migration vers max_memory ») : on ne
    réécrit pas la spec, mais on prévient l'utilisateur que sa limite dépasse le
    plafond du nœud et sera bornée au prochain démarrage/recreate. None quand
    rien ne change (nœud sans plafond, ou demande déjà conforme).
    """
    from ..config.models import borner_memoire
    from ..config.store import load_global

    g = load_global()
    host = next((h for h in g.hosts if h.name == host_name), None)
    plafond = host.max_memory if host else ""
    if not plafond:
        return None
    demande = (memory_limit or "").strip() or g.devpod.defaults.memory_limit
    borne = borner_memoire(demande, plafond)
    return borne if borne != demande else None


@router.get("/workspaces")
async def list_workspaces(user: UserInfo = Depends(require_user)) -> list[dict[str, object]]:
    cfg = await load_user(user.login)
    entrees: list[dict[str, object]] = []
    for ws in cfg.workspaces:
        entree = ws.model_dump(mode="json")
        borne = _memory_borne(ws.host, ws.memory_limit)
        if borne is not None:
            entree["memory_borne"] = borne
        entrees.append(entree)
    return entrees


def _borner_memoire(host_name: str, memory_limit: str) -> str:
    """La mémoire effective d'un workspace, bornée au plafond du nœud cible.

    Le plafond `hosts.max_memory` protège le nœud du dépassement d'UN workspace
    (fiche 1dae864d) :
    - nœud sans plafond → rien ne change, la valeur demandée passe telle quelle ;
    - demande VIDE sur un nœud qui plafonne → n'est plus « aucune limite », elle
      vaut le plafond du nœud ;
    - demande au-dessus du plafond → refus 422 au moment de la saisie, plutôt
      qu'un `up` qui échoue dix minutes plus tard.
    """
    from ..config.models import memoire_depasse_plafond
    from ..config.store import load_global

    host = next((h for h in load_global().hosts if h.name == host_name), None)
    plafond = host.max_memory if host else ""
    if not plafond:
        return memory_limit
    demande = (memory_limit or "").strip()
    if not demande:
        return plafond
    if memoire_depasse_plafond(demande, plafond):
        raise HTTPException(
            status_code=422,
            detail=(
                f"La mémoire demandée ({demande}) dépasse le plafond du nœud "
                f"{host_name!r} ({plafond})."
            ),
        )
    return demande


async def enregistrer_workspace(
    workspace: WorkspaceSpec, user: UserInfo, conn: AsyncConnection
) -> dict[str, object]:
    """Le SEUL chemin d'enregistrement REST d'un workspace — partagé avec la
    création depuis un template : bornage mémoire, verrou, unicité du nom,
    quota du forfait vérifié et écrit dans la même transaction."""
    # Bornage mémoire AVANT tout : un refus se dit à la saisie, et une demande
    # vide se voit remplacée par le plafond du nœud si celui-ci en déclare un.
    workspace = workspace.model_copy(
        update={"memory_limit": _borner_memoire(workspace.host, workspace.memory_limit)}
    )
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        if any(ws.name == workspace.name for ws in cfg.workspaces):
            raise HTTPException(
                status_code=409, detail=f"Workspace {workspace.name!r} already exists"
            )
        cfg.workspaces.append(workspace)
        # Quota du forfait : vérification et écriture dans la MÊME transaction,
        # sous un verrou par machine cible — deux créations concurrentes qui
        # voient chacune la dernière place ne doivent pas passer toutes les
        # deux, et le verrou par login ne couvre pas owner + invité.
        await verrouiller_creation(workspace.host, conn)
        try:
            await verifier_quota_creation(user.login, workspace.host, conn)
        except QuotaDepasse as exc:
            # 403 avec le message de la règle, tel quel : il nomme le quota
            # atteint et ce qui y répond (machine plus grosse, ou forfait).
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        await save_user_db(user.login, cfg, conn)
    _log.info("workspace_added", login=user.login, name=workspace.name)
    return workspace.model_dump(mode="json")


@router.post("/workspaces", status_code=201)
async def add_workspace(
    workspace: WorkspaceSpec,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    return await enregistrer_workspace(workspace, user, conn)


class _WorkspacePatch(BaseModel):
    """Édition de la config d'un workspace existant — champs tous optionnels.

    Seuls les champs EXPLICITEMENT fournis sont appliqués (`model_fields_set`) :
    un PATCH partiel ne doit jamais effacer le reste de la config, même erreur que
    celle déjà corrigée côté `POST /workspaces/{name}/up`. `name` est absent
    volontairement : renommer changerait le ws_id, donc l'identité du conteneur.
    """

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    branch: str | None = None
    git_credential: str | None = None
    host: str | None = None
    recipes: list[str] | None = None
    start_recipes: list[str] | None = None
    init_recipes: list[str] | None = None
    recipe_volumes: list[str] | None = None
    extra_sources: list[SourceSpec] | None = None
    profile: ProfileRef | None = None
    agents: list[str] | None = None
    memory_limit: str | None = None
    env: dict[str, str] | None = None
    ssh_key: bool | None = None
    default_start: str | None = None


@router.patch("/workspaces/{name}")
async def patch_workspace(
    name: str,
    body: _WorkspacePatch,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Édite la configuration d'un workspace existant, sans rien redémarrer.

    Persiste la nouvelle spec et RETOURNE l'impact : `requires_recreate` liste les
    champs qui n'auront d'effet qu'après reconstruction de l'image (recettes,
    profil, mémoire…), `requires_restart` ceux qu'un simple stop/start applique.
    L'appelant décide — on ne recrée JAMAIS un conteneur dans le dos de
    l'utilisateur (une recréation détruit le travail non commité).
    """
    from ..devpod.spec_changes import added_recipes, requires_recreate, requires_restart

    patch = body.model_dump(exclude_unset=True)
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        idx = next((i for i, ws in enumerate(cfg.workspaces) if ws.name == name), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"Workspace {name!r} introuvable")
        current = cfg.workspaces[idx]
        try:
            updated = WorkspaceSpec.model_validate({**current.model_dump(), **patch})
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Même bornage qu'à la création : éditer la mémoire au-dessus du plafond
        # du nœud est refusé ici, pas découvert au prochain recreate.
        borne = _borner_memoire(updated.host, updated.memory_limit)
        if borne != updated.memory_limit:
            updated = updated.model_copy(update={"memory_limit": borne})
        recreate = requires_recreate(current, updated)
        restart = requires_restart(current, updated)
        added = added_recipes(current, updated)
        if not recreate and not restart and updated == current:
            # Rien n'a bougé : on évite une écriture (et un event) inutiles.
            return {
                "spec": current.model_dump(mode="json"),
                "requires_recreate": [],
                "requires_restart": [],
                "added_recipes": [],
            }
        cfg.workspaces[idx] = updated
        await save_user(user.login, cfg)
    _log.info(
        "workspace_config_updated",
        login=user.login,
        name=name,
        changed=sorted(patch),
        requires_recreate=recreate,
        added_recipes=added,
    )
    return {
        "spec": updated.model_dump(mode="json"),
        "requires_recreate": recreate,
        "requires_restart": restart,
        "added_recipes": added,
    }


class _WorkspaceAgentsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[str]


@router.patch("/workspaces/{name}/agents")
async def patch_workspace_agents(
    name: str,
    body: _WorkspaceAgentsPatch,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Choix des agent_types à mapper (spec 35) — persiste sans redémarrer.

    Le mapping effectif (génération des fichiers host, bind mount) n'a lieu
    qu'au prochain `up` du workspace ; cet endpoint ne fait que sauvegarder
    la sélection pour ce `up` à venir.
    """
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        idx = next((i for i, ws in enumerate(cfg.workspaces) if ws.name == name), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"Workspace {name!r} introuvable")
        try:
            updated = WorkspaceSpec.model_validate(
                {**cfg.workspaces[idx].model_dump(), "agents": body.agents}
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        cfg.workspaces[idx] = updated
        await save_user(user.login, cfg)
    _log.info("workspace_agents_updated", login=user.login, name=name, agents=body.agents)
    return updated.model_dump(mode="json")


@router.get("/git/branches")
async def list_git_branches(
    url: str,
    credential: str = "",
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Retourne les branches d'un dépôt git distant via git ls-remote."""
    returncode, stdout, stderr = await run_git_ls_remote(url, credential, user.login)

    if returncode != 0:
        err = stderr.decode(errors="replace").strip() if stderr else ""
        _log.warning(
            "git_ls_remote_failed",
            login=user.login,
            url=url,
            returncode=returncode,
            stderr=err,
        )
        if (
            "terminal prompts disabled" in err
            or "could not read Username" in err
            or "Authentication failed" in err
        ):
            detail = (
                "Authentification git échouée."
                " Vérifiez le token et ses permissions d'accès au dépôt."
            )
        elif "Repository not found" in err or "not found" in err.lower():
            detail = (
                "Dépôt introuvable ou accès refusé. Vérifiez l'URL et les permissions du token."
            )
        elif "Could not resolve host" in err or "unable to resolve" in err.lower():
            detail = "Hôte introuvable. Vérifiez l'URL du dépôt."
        elif "timed out" in err.lower():
            detail = "Délai dépassé lors de la connexion au dépôt."
        else:
            detail = err or "git ls-remote a échoué"
        raise HTTPException(status_code=422, detail=detail)

    branches: list[str] = []
    default: str | None = None
    for line in stdout.decode(errors="replace").splitlines():
        if line.startswith("ref: refs/heads/") and "\t" in line:
            default = line.split("\t")[0][len("ref: refs/heads/") :]
        elif "\trefs/heads/" in line:
            branches.append(line.split("\t")[1][len("refs/heads/") :])

    if default and default in branches:
        branches.remove(default)
        branches.insert(0, default)

    _log.info("git_branches_listed", login=user.login, url=url, count=len(branches))
    return {"branches": branches, "default": default}


class _GitCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    kind: Literal["ssh", "token"]
    username: str = ""
    cert_slug: str = ""  # si kind=ssh : slug dans harpo_certificates
    secret_slug: str = ""  # si kind=token : slug dans harpo_secrets


@router.get("/git-credentials")
async def list_git_credentials(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, object]]:
    cfg = await load_user(user.login)
    return [
        {"name": c.name, "host": c.host, "kind": c.kind, "username": c.username}
        for c in cfg.git_credentials
    ]


@router.post("/git-credentials", status_code=201)
async def add_git_credential(
    body: _GitCredentialCreate,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    if not _CRED_NAME_RE.fullmatch(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid credential name: {body.name!r}")
    host = body.host.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not host:
        raise HTTPException(status_code=422, detail="host is required")

    cfg = await load_user(user.login)
    if any(c.name == body.name for c in cfg.git_credentials):
        raise HTTPException(status_code=409, detail=f"Credential {body.name!r} already exists")

    key_path = ""
    token = ""

    if body.kind == "ssh":
        if not body.cert_slug:
            raise HTTPException(status_code=422, detail="cert_slug requis pour un credential SSH")
        try:
            pem = await cert_svc.reveal_private_key(user.login, _sid(request), body.cert_slug, conn)
        except cert_svc.VaultLocked:
            raise HTTPException(status_code=403, detail="vault_locked") from None
        except cert_svc.CertNotFound:
            raise HTTPException(status_code=404, detail="cert_not_found") from None
        key_dir = safe_user_path(user.login, "keys", "git", body.name)
        key_dir.mkdir(parents=True, exist_ok=True)
        key_file = key_dir / "id_ed25519"
        key_file.write_text(pem.strip() + "\n", encoding="utf-8")
        key_file.chmod(0o600)
        key_path = str(key_file)
    elif body.kind == "token":
        if not body.secret_slug:
            raise HTTPException(status_code=422, detail="secret_slug requis pour un credential PAT")
        try:
            token = await secret_svc.reveal_secret(
                user.login, _sid(request), body.secret_slug, conn
            )
        except secret_svc.VaultLocked:
            raise HTTPException(status_code=403, detail="vault_locked") from None
        except secret_svc.SecretNotFound:
            raise HTTPException(status_code=404, detail="secret_not_found") from None

    new_cred = GitCredential(
        name=body.name,
        host=host,
        kind=body.kind,
        key_path=key_path,
        username=body.username.strip(),
        token=token,
    )
    # Re-load sous verrou (bug 009) : le reveal vault ci-dessus est une I/O réseau,
    # on ne tient pas le verrou pendant — on revalide l'unicité sur l'état frais.
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        if any(c.name == body.name for c in cfg.git_credentials):
            raise HTTPException(status_code=409, detail=f"Credential {body.name!r} already exists")
        cfg.git_credentials.append(new_cred)
        await save_user(user.login, cfg)
    _log.info("git_credential_added", login=user.login, name=body.name, kind=body.kind)
    return {"name": body.name, "host": host, "kind": body.kind}


class _GitCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_name: str | None = None
    host: str | None = None
    kind: Literal["ssh", "token"] | None = None
    username: str | None = None
    cert_slug: str | None = None  # si kind=ssh : nouveau cert depuis harpo_certificates
    secret_slug: str | None = None  # si kind=token : nouveau secret depuis harpo_secrets


@router.patch("/git-credentials/{name}")
async def patch_git_credential(
    name: str,
    body: _GitCredentialUpdate,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    cfg = await load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")

    if body.new_name is not None:
        if not _CRED_NAME_RE.fullmatch(body.new_name):
            raise HTTPException(
                status_code=422, detail=f"Invalid credential name: {body.new_name!r}"
            )
        if body.new_name != name and any(c.name == body.new_name for c in cfg.git_credentials):
            raise HTTPException(
                status_code=409, detail=f"Credential {body.new_name!r} already exists"
            )

    effective_kind = body.kind if body.kind is not None else cred.kind
    effective_name = body.new_name if body.new_name is not None else name
    effective_host = (
        body.host.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if body.host is not None
        else cred.host
    )
    effective_username = body.username.strip() if body.username is not None else cred.username

    if body.host is not None and not effective_host:
        raise HTTPException(status_code=422, detail="host is required")

    new_key_path = cred.key_path
    new_token = cred.token
    key_to_delete: Path | None = None

    if effective_kind == "ssh":
        new_token = ""
        if body.cert_slug is not None:
            # Nouveau certificat fourni : révéler et réécrire le fichier
            try:
                pem = await cert_svc.reveal_private_key(
                    user.login, _sid(request), body.cert_slug, conn
                )
            except cert_svc.VaultLocked:
                raise HTTPException(status_code=403, detail="vault_locked") from None
            except cert_svc.CertNotFound:
                raise HTTPException(status_code=404, detail="cert_not_found") from None
            old_key_path = cred.key_path
            key_dir = safe_user_path(user.login, "keys", "git", effective_name)
            key_dir.mkdir(parents=True, exist_ok=True)
            key_file = key_dir / "id_ed25519"
            key_file.write_text(pem.strip() + "\n", encoding="utf-8")
            key_file.chmod(0o600)
            new_key_path = str(key_file)
            if old_key_path and old_key_path != new_key_path:
                key_to_delete = Path(old_key_path)
        elif cred.kind != "ssh":
            raise HTTPException(status_code=422, detail="cert_slug requis pour passer en mode SSH")
        elif effective_name != name and cred.key_path:
            # Renommage sans changement de cert : déplacer le fichier
            old_file = Path(cred.key_path)
            new_key_dir = safe_user_path(user.login, "keys", "git", effective_name)
            new_key_dir.mkdir(parents=True, exist_ok=True)
            new_key_file = new_key_dir / "id_ed25519"
            if old_file.exists():
                shutil.copy2(str(old_file), str(new_key_file))
                new_key_file.chmod(0o600)
                key_to_delete = old_file
            new_key_path = str(new_key_file)
    else:
        new_key_path = ""
        if cred.kind == "ssh" and cred.key_path:
            key_to_delete = Path(cred.key_path)
        if body.secret_slug is not None:
            # Nouveau secret fourni : révéler et stocker
            try:
                new_token = await secret_svc.reveal_secret(
                    user.login, _sid(request), body.secret_slug, conn
                )
            except secret_svc.VaultLocked:
                raise HTTPException(status_code=403, detail="vault_locked") from None
            except secret_svc.SecretNotFound:
                raise HTTPException(status_code=404, detail="secret_not_found") from None
        elif cred.kind != "token":
            raise HTTPException(
                status_code=422, detail="secret_slug requis pour passer en mode PAT"
            )

    updated = GitCredential(
        name=effective_name,
        host=effective_host,
        kind=effective_kind,
        key_path=new_key_path,
        username=effective_username,
        token=new_token,
    )
    # Re-load sous verrou (bug 009) : les reveals vault ci-dessus sont des I/O
    # réseau, on ne tient pas le verrou pendant — mutation sur l'état frais.
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        if not any(c.name == name for c in cfg.git_credentials):
            raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")
        if effective_name != name and any(c.name == effective_name for c in cfg.git_credentials):
            raise HTTPException(
                status_code=409, detail=f"Credential {effective_name!r} already exists"
            )
        cfg.git_credentials = [updated if c.name == name else c for c in cfg.git_credentials]

        if effective_name != name:
            for ws in cfg.workspaces:
                if ws.git_credential == name:
                    ws.git_credential = effective_name
                for src in ws.extra_sources:
                    if src.git_credential == name:
                        src.git_credential = effective_name

        await save_user(user.login, cfg)

    if key_to_delete and key_to_delete.exists():
        key_to_delete.unlink()
        pub_to_delete = key_to_delete.parent / "id_ed25519.pub"
        if pub_to_delete.exists():
            pub_to_delete.unlink()

    _log.info("git_credential_updated", login=user.login, name=name, new_name=effective_name)
    return {"name": effective_name, "host": effective_host, "kind": effective_kind}


@router.delete("/git-credentials/{name}")
async def delete_git_credential(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        cred = next((c for c in cfg.git_credentials if c.name == name), None)
        if not cred:
            raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")
        cfg.git_credentials = [c for c in cfg.git_credentials if c.name != name]
        await save_user(user.login, cfg)
    if cred.kind == "ssh" and cred.key_path:
        key_file = Path(cred.key_path)
        if key_file.exists():
            key_file.unlink()
        pub_file = key_file.parent / "id_ed25519.pub"
        if pub_file.exists():
            pub_file.unlink()
    _log.info("git_credential_deleted", login=user.login, name=name)
    return {"deleted": name}


@router.post("/git-credentials/{name}/test")
async def test_git_credential_connection(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Teste l'authentification d'un credential sur son host (sans dépôt réel)."""
    cfg = await load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")
    ok, message = await probe_git_credential(name, cred.host, user.login)
    _log.info("git_credential_tested", login=user.login, name=name, ok=ok)
    return {"ok": ok, "message": message}


@router.delete("/workspaces/{name}")
async def delete_workspace(name: str, user: UserInfo = Depends(require_user)) -> dict[str, object]:
    async with user_config_lock(user.login):
        cfg = await load_user(user.login)
        before = len(cfg.workspaces)
        cfg.workspaces = [ws for ws in cfg.workspaces if ws.name != name]
        if len(cfg.workspaces) == before:
            raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
        await save_user(user.login, cfg)
    _log.info("workspace_deleted", login=user.login, name=name)
    return {"deleted": name}
