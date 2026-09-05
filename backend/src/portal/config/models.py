from __future__ import annotations

import re
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from portal.billing.config import BillingConfig
from portal.profiles.models import Scope


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warning", "error"] = "info"
    format: Literal["text", "json"] = "text"
    output: str = ""


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listen: str = "0.0.0.0:8080"
    base_domain: str
    external_url: str
    dev_mode: bool = False
    # En dev, l'URL publique (external_url) passe par Cloudflare qui bloque les
    # ports non-standard.  workspace_host permet de spécifier l'IP/hostname
    # direct de la VM pour les URLs de workspace (ex : "192.168.10.50").
    workspace_host: str = ""
    # Domaine DNS local (ex. "home.lan") ajouté au nom d'une machine de test pour
    # re-résoudre son IP DHCP. Vide → on résout le nom seul.
    local_domain: str = ""
    # Sous-domaine fixe pour le proxy VS Code (ex. "vs-dev.yoops.org"). Quand renseigné,
    # un seul sous-domaine sert tous les workspaces ; Caddy résout l'upstream par cookie/session.
    vs_proxy_domain: str = ""
    # Domaine du cookie de session (ex. "yoops.org"). Obligatoire quand portail et
    # workspaces VS Code n'ont qu'un ancêtre commun (dev.yoops.org + vs-dev.yoops.org).
    # Vide → base_domain est utilisé par défaut.
    cookie_domain: str = ""
    # Durées de session paramétrables depuis l'admin (secondes). 0 = hériter du défaut
    # (settings/env). session_max_age = idle GLISSANT du cookie ; session_absolute_max_age
    # = plafond absolu depuis le login (refresh des rôles). Cf. auth/rbac + app.py.
    session_max_age: int = 0
    session_absolute_max_age: int = 0
    log: LogConfig = Field(default_factory=LogConfig)


_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](-?[a-z0-9])*(\.[a-z0-9](-?[a-z0-9])*)*$", re.IGNORECASE
)


def validate_network(
    base_domain: str,
    external_url: str,
    workspace_host: str,
    vs_proxy_domain: str = "",
    cookie_domain: str = "",
) -> dict[str, str]:
    """Valide/normalise la config réseau saisie par l'admin.

    Le vide est autorisé (routage par sous-domaine désactivé). Si renseigné :
    base_domain/workspace_host/vs_proxy_domain doivent être un hôte valide,
    external_url une URL absolue http(s). Retourne les valeurs nettoyées.
    """
    bd = base_domain.strip()
    if bd and not _HOSTNAME_RE.fullmatch(bd):
        raise ValueError(f"base_domain invalide: {base_domain!r}")
    eu = external_url.strip().rstrip("/")
    if eu:
        parsed = urlparse(eu)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"external_url doit être une URL absolue http(s): {external_url!r}")
    wh = workspace_host.strip()
    if wh and not _HOSTNAME_RE.fullmatch(wh):
        raise ValueError(f"workspace_host invalide: {workspace_host!r}")
    vpd = vs_proxy_domain.strip()
    if vpd and not _HOSTNAME_RE.fullmatch(vpd):
        raise ValueError(f"vs_proxy_domain invalide: {vs_proxy_domain!r}")
    cd = cookie_domain.strip() if cookie_domain else ""
    if cd and not _HOSTNAME_RE.fullmatch(cd):
        raise ValueError(f"cookie_domain invalide: {cookie_domain!r}")
    return {
        "base_domain": bd,
        "external_url": eu,
        "workspace_host": wh,
        "vs_proxy_domain": vpd,
        "cookie_domain": cd,
    }


class OidcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    client_id: str
    client_secret: str

    @field_validator("issuer", "client_id", "client_secret", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "roles"])
    role_claim: str = "realm_access.roles"
    admin_role: str = "admin"
    user_role: str = "dev"
    username_claim: str = "preferred_username"
    # Quand False : le login local break-glass (LOCAL_USER/.env) est désactivé,
    # même si LOCAL_USER/LOCAL_PASSWORD_HASH sont présents dans .env.
    allow_local_auth: bool = True
    # Déconnexion propagée à l'IdP (RP-Initiated Logout, OIDC Session Management).
    # Sans elle, se déconnecter du portail ne ferme QUE la session locale : le
    # cookie SSO Keycloak survit, et le clic suivant sur « OIDC » ré-authentifie
    # en silence sans jamais afficher la mire — impossible de changer de compte.
    # ⚠ La déconnexion est propagée à TOUTES les applications du realm (Grafana,
    # Termix…) : c'est le comportement attendu d'un logout SSO, mais il se coupe
    # ici si on préfère ne fermer que la session du portail.
    sso_logout: bool = True


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oidc: OidcConfig


class HarpocrateGlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    api_key: str = ""
    base_path: str = "devpod"


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["harpocrate", "inline"] = "inline"
    harpocrate: HarpocrateGlobalConfig = Field(default_factory=HarpocrateGlobalConfig)


# Format docker : entier + unité b/k/m/g optionnelle (ex. 4g, 512m). La casse
# est normalisée en minuscule avant validation.
_MEMORY_LIMIT_RE = re.compile(r"^[0-9]+[bkmg]?$")


def _validate_memory_limit(v: str) -> str:
    v = v.strip().lower()
    if v and not _MEMORY_LIMIT_RE.fullmatch(v):
        raise ValueError(
            f"memory limit {v!r} invalide — entier + unité optionnelle b/k/m/g (ex. 4g, 512m)"
        )
    return v


class DevpodDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "2h"
    dotfiles: str = ""
    # Limite mémoire par défaut des conteneurs workspace (enabler 59864c37) :
    # docker --memory, appliquée à la (re)construction du conteneur. 900m par
    # décision d'exploitation (2026-07-26) ; surchargeable globalement (admin)
    # et par workspace. "" = aucune limite.
    memory_limit: str = "900m"

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_limit(cls, v: str) -> str:
        return _validate_memory_limit(v)


class DevpodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binary: str = "/usr/local/bin/devpod"
    defaults: DevpodDefaults = Field(default_factory=DevpodDefaults)
    client_cert_path: str = "/data/certs/portal"


_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
# Meme forme que la `key` de `RecipeMeta`, qu'on reference ici.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ProfileRecipe(BaseModel):
    """Une recette a poser sur la machine, avec ses parametres.

    Referencee par `key` — l'UUID stable de `RecipeMeta` — et non par `id` : un
    identifiant se renomme au catalogue, la cle survit. C'est deja le choix fait
    par `installs_after`.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    # Valeurs des options declarees par la recette. Choisir une recette sans
    # pouvoir la parametrer n'aurait pas de sens : l'AVD, la RAM, le niveau
    # d'API se decident au profil. Validees contre la declaration a
    # l'application (`resolve_options`).
    options: dict[str, str] = Field(default_factory=dict)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _UUID_RE.fullmatch(v):
            raise ValueError(f"recipe key {v!r} must be a valid UUID")
        return v.lower()


class ProfileService(BaseModel):
    """Un service Docker a lancer au demarrage de la machine.

    On reference un TEMPLATE COMPOSE existant — ceux que « Lancer un service »
    deploie deja a la main — plutot qu'une image brute : le template porte son
    compose, ses parametres types et sa version. Reinventer une liste d'images
    ici dupliquerait tout cela pour moins bien.
    """

    model_config = ConfigDict(extra="forbid")

    template_id: str
    # Nom du deploiement : projet docker compose et repertoire distant. Deux
    # instances du meme template sur une machine doivent pouvoir coexister,
    # d'ou un nom distinct du template. Vide = celui du template.
    deployment_id: str = ""
    # Valeurs des `parameters` declares par le template.
    params: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def defaut_deployment_id(self) -> ProfileService:
        if not self.deployment_id:
            object.__setattr__(self, "deployment_id", self.template_id)
        return self

    @field_validator("template_id", "deployment_id")
    @classmethod
    def validate_slugs(cls, v: str) -> str:
        if v and not _PROFILE_SLUG_RE.fullmatch(v):
            raise ValueError(f"{v!r} must match {_PROFILE_SLUG_RE.pattern}")
        return v


class MachineProfile(BaseModel):
    """Modele de machine : parametres figes + recettes a poser.

    Remplace le jeu unique `test_host_params` porte par le type d'hyperviseur.
    Les parametres n'ont de sens que contre la spec d'un type donne — un profil
    « 8 Go / cpu host » ne veut rien dire hors de Proxmox — d'ou le rattachement
    obligatoire.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    label: str
    # Meme vocabulaire que `HostConfig.usage`, a un detail pres : la machine de
    # test s'ecrit `test` ici (valeur historique, deja en base) et `tests` la-bas.
    # Seul `test` est exploite a la creation ; les autres se declarent des
    # maintenant, l'usage viendra.
    machine_type: Literal["test", "ressources", "workspaces", "autres"] = "test"
    hypervisor_type: str
    # Args du script de creation, tels que declares par la spec du type.
    params: dict[str, str] = Field(default_factory=dict)
    # Appliquees DANS CET ORDRE apres la creation : une dependance se pose avant
    # celle qui l'utilise.
    recipes: list[ProfileRecipe] = Field(default_factory=list)
    # Services Docker lances au demarrage, dans l'ordre declare.
    services: list[ProfileService] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _PROFILE_SLUG_RE.fullmatch(v):
            raise ValueError(f"slug {v!r} must match {_PROFILE_SLUG_RE.pattern}")
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        # Le slug est technique ; c'est le label que l'utilisateur lit.
        if not v.strip():
            raise ValueError("label must not be empty")
        return v.strip()

    @field_validator("hypervisor_type")
    @classmethod
    def validate_hypervisor_type(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("hypervisor_type is required: params are typed by the script spec")
        return v.strip()

    @field_validator("recipes")
    @classmethod
    def refuse_doublon(cls, v: list[ProfileRecipe]) -> list[ProfileRecipe]:
        """Deux entrees pour une meme recette : la derniere gagnerait en silence,
        et rien ne dirait laquelle de ses options s'applique."""
        vues: set[str] = set()
        for recette in v:
            if recette.key in vues:
                raise ValueError(f"doublon de recette dans le profil : {recette.key}")
            vues.add(recette.key)
        return v

    @field_validator("services")
    @classmethod
    def refuse_doublon_de_deploiement(cls, v: list[ProfileService]) -> list[ProfileService]:
        """Deux deploiements de meme nom, c'est le meme repertoire distant et le
        meme projet compose : le second ecraserait le premier en silence."""
        vus: set[str] = set()
        for service in v:
            if service.deployment_id in vus:
                raise ValueError(f"doublon de deploiement dans le profil : {service.deployment_id}")
            vus.add(service.deployment_id)
        return v


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    # Contrat de driver (épic provisionnement, ticket 4) : provider = type de
    # driver qui a monté la machine, provider_ref = référence OPAQUE que seul
    # ce driver sait relire (le portail la stocke et la repasse, jamais ne la
    # lit). vmid/proxmox_node ci-dessus sont le chemin historique : ils
    # disparaîtront à l'étape 3 de la migration (cf. cadrage), une fois le
    # chemin driver éprouvé en production de test.
    provider: str = ""
    provider_ref: dict[str, Any] = Field(default_factory=dict)
    # Garde-fous cloud (ticket 11) — domaine du portail, posés par l'exécuteur
    # au provisionnement (jamais relus depuis provider_ref, qui est opaque) :
    # estimation grossière €/mois pour le plafond, et TTL (ISO 8601, vide =
    # permanent) qui déclenche une ALERTE, jamais un arrêt automatique.
    cost_estimate_eur_month: float = 0.0
    expires_at: str = ""
    # Références vers harpo_* (slugs)
    ci_password_secret_slug: str = ""
    host_cert_slug: str = ""
    # Certificat client mTLS (docker-tls) : slug d'une entrée tls-* du
    # gestionnaire de certificats. Vide = répertoire partagé (client_cert_path).
    docker_cert_slug: str = ""
    # Préférences de stockage des secrets
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str = ""
    # Destination du host : workspaces, tests, portail (machine du portail),
    # ressources (service partagé permanent, sans workspace propriétaire — spec 33),
    # ou autres (inventaire simple : ni workspaces, ni services compose).
    usage: Literal["workspaces", "tests", "portail", "ressources", "autres"] = "workspaces"
    # Profil avec lequel la machine a ete montee. Sans cette reference, on ne
    # sait pas six mois plus tard ce qui a ete pose dessus ni avec quels
    # parametres. Vide pour les machines anterieures aux profils.
    profile_slug: str = ""
    # Nombre de workspaces que la machine SUPPORTE sans planter. Donnee
    # d'exploitation de la MACHINE, pas du profil : editer un profil ne
    # redimensionne aucune VM deja montee, et un noeud enrole a la main n'a
    # aucun profil. Le profil sert de valeur par defaut au provisionnement, pas
    # de tutelle. `None` = non renseigne, ce qui n'est ni zero ni l'infini.
    capacity_workspaces: int | None = Field(default=None, ge=0)
    # Cette machine peut-elle accueillir les workspaces d'offres mutualisees ?
    # Faux par defaut : ouvrir un noeud au public est un acte delibere.
    accepts_mutualise: bool = False
    # Hyperviseur qui a monte la machine. PROVENANCE, pas contrainte : le lien
    # par nom de noeud (`proxmox_node`) est ambigu des que deux hyperviseurs
    # partagent un noeud, et `pve` est le nom d'hote par defaut de Proxmox.
    # Vide = provenance inconnue : machine enrolee a la main, ou montee avant
    # que cette colonne existe. Ni une erreur, ni un hyperviseur par defaut.
    hypervisor: str = ""


_PROXMOX_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


_ACTION_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


#: Slug RÉSERVÉ : la variable qui porte la capacité d'accueil d'une machine.
#: Le portail la lit pour savoir combien de workspaces la machine supporte sans
#: planter. Ce n'est pas une valeur magique cachée dans le code — c'est une
#: variable déclarée comme les autres sur le type d'hyperviseur, que l'IHM sait
#: proposer d'un clic pour éviter une faute de frappe.
CAPACITY_VARIABLE = "capacity_workspaces"

# Les variables acceptent l'underscore, contrairement aux autres slugs : elles
# nomment des grandeurs (`capacity_workspaces`) et non des ressources, et le
# nom doit rester identique à celui de la colonne qu'il alimente.
_VARIABLE_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,38}[a-z0-9])?$")


class HypervisorVariable(BaseModel):
    """Variable déclarée par un type d'hyperviseur, valuée par un profil de host.

    Le type d'hyperviseur dit CE QUI EXISTE, le profil de host dit COMBIEN. La
    déclaration vit ici et pas dans le code parce qu'elle dépend de l'hyperviseur
    et de ce que l'exploitant sait de ses machines : personne d'autre que lui ne
    peut dire combien de workspaces tient un gabarit donné.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    slug: str
    type: Literal["int", "string"] = "string"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _VARIABLE_SLUG_RE.fullmatch(v):
            raise ValueError(f"slug {v!r} must match ^[a-z0-9]([a-z0-9_-]{{0,38}}[a-z0-9])?$")
        return v

    def valider_valeur(self, valeur: str) -> str:
        """Valeur acceptable pour cette variable, ou `ValueError`.

        Une variable `int` qui reçoit « beaucoup » ne se découvrirait qu'à la
        création de la machine, trop tard et loin de la saisie.
        """
        brut = valeur.strip()
        if self.type == "int":
            try:
                int(brut)
            except ValueError:
                raise ValueError(
                    f"variable {self.slug!r} attend un entier, reçu {valeur!r}"
                ) from None
        return brut


class HypervisorAction(BaseModel):
    """Script supplémentaire attaché à un type d'hyperviseur.

    La création et la destruction sont deux actions parmi d'autres — redémarrer,
    étendre un disque, prendre un snapshot. Elles se déclarent ici plutôt que
    dans le code : chacune est un descripteur JSON du même format que le script
    de création, donc paramétrable et exécutable de la même façon.

    Le `slug` est QUALIFIÉ par le type (`<type>-<slug>`) : deux types peuvent
    proposer un « reboot » sans que leurs actions se confondent.

    La `cible` dit sur QUOI l'action s'applique. Les deux natures ne se
    déclenchent pas au même endroit — l'une depuis la liste des hyperviseurs,
    l'autre depuis la ligne d'un nœud — et rien d'autre ne permet de les
    distinguer : un `reboot` sans cible pourrait aussi bien redémarrer
    l'hyperviseur que la VM.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    slug: str
    # URL du descripteur JSON, même format que `add_script`.
    script: str = ""
    # `machine` par défaut : les types enregistrés avant l'introduction du champ
    # ne déclarent que des actions de VM (mémoire, disque), et c'est aussi ce que
    # produit le script de création. Un défaut `hyperviseur` reclasserait à tort
    # tout l'existant.
    cible: Literal["hyperviseur", "machine"] = "machine"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _ACTION_SLUG_RE.fullmatch(v):
            raise ValueError(f"slug {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


def qualify_action_slug(type_name: str, slug: str) -> str:
    """`<type>-<slug>`, sans redoubler le préfixe s'il est déjà là.

    Idempotent : ré-enregistrer un type ne doit pas transformer `proxmox-reboot`
    en `proxmox-proxmox-reboot`.
    """
    prefixe = f"{type_name}-"
    return slug if slug.startswith(prefixe) else prefixe + slug


class HypervisorType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    name: str
    add_script: str = ""
    destroy_script: str = ""
    # Bascule du chemin de création (ticket 9) : vide = scripts add/destroy
    # ci-dessus (chemin historique) ; « proxmox » = driver IaC derrière le
    # contrat. Revenir au script = vider ce champ, rien d'autre.
    provisioning_driver: str = ""
    # Valeurs par défaut des args pour créer un host de test (sauf l'identifiant).
    test_host_params: dict[str, str] = Field(default_factory=dict)
    # Actions supplémentaires (au-delà de créer/détruire), déclarées par l'admin.
    actions: list[HypervisorAction] = Field(default_factory=list)
    # Variables que les profils de host de ce type auront à renseigner. Le type
    # déclare ce qui existe, le profil de host donne les valeurs.
    variables: list[HypervisorVariable] = Field(default_factory=list)

    @field_validator("variables")
    @classmethod
    def validate_variables(cls, v: list[HypervisorVariable]) -> list[HypervisorVariable]:
        # Deux variables de même slug rendraient la valeur retenue dépendante de
        # l'ordre de saisie : refus à la déclaration.
        slugs = [var.slug for var in v]
        doublons = sorted({s for s in slugs if slugs.count(s) > 1})
        if doublons:
            raise ValueError(f"variables en double : {', '.join(doublons)}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _PROXMOX_NAME_RE.fullmatch(v):
            raise ValueError(f"name {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


class Hypervisor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key_path: str
    pve_node: str = "pve"
    hypervisor_type: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _PROXMOX_NAME_RE.fullmatch(v):
            raise ValueError(f"name {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


class CaddyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_api: str = "http://caddy:2019"
    portal_host: str = "portal"


class CloudflareManagerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    api_key: str = ""


class BastionConfig(BaseModel):
    """Bastion SSH → Termix (éditable via l'IHM admin, plus d'.env à la main).

    `enabled` pilote le sshd bastion (démarré/arrêté à chaud par l'app). Le provisioning
    Termix (credential+host+partage) n'est actif que si api_url + host + role sont posés.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_url: str = ""  # URL externe Termix (ex. https://termix.yoops.org)
    host: str = ""  # IP/host que Termix vise en SSH (IP LAN du portail)
    port: int = 2222
    role: str = ""  # nom du rôle Termix cible du partage
    apikey_secret: str = "termix-apikey"  # slug du secret système portant l'apikey tmx_


class LogsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    loki_push_url: str | None = None
    loki_query_url: str | None = None
    # TSDB des metriques machine (endpoint `remote_write`). Vit dans ce bloc
    # parce que c'est le meme sujet — l'observabilite du parc — et que les
    # collecteurs des deux chaines recoivent leurs variables du meme endroit.
    # Non renseignee : le portail n'injecte pas METRICS_URL, les collecteurs de
    # metriques refusent de demarrer plutot que de tourner dans le vide.
    metrics_push_url: str | None = None
    grafana_url: str | None = None
    module: str = "devpod"
    push_token: str | None = None  # littéral ou ${vault://...}/${env://...}
    # Client OAuth Keycloak du login SSO de Grafana lui-même — distinct de
    # push_token qui authentifie les collecteurs Alloy vers Loki. Auth/token/
    # userinfo URL dérivées de auth.oidc.issuer (même realm Keycloak).
    grafana_oauth_client_id: str = "agflow-grafana"
    grafana_oauth_client_secret: str | None = None


class EventsProducerConfig(BaseModel):
    """Producteur d'events vers le module workflow (contrat producteur d'events).

    Le portail émet déjà des events applicatifs en interne (bus `portal.events`) ;
    ce bloc active leur relais signé HMAC vers le module workflow. `source_id` est
    l'UUID attribué par le workflow à l'enregistrement de la source ; `secret_slug`
    référence le secret HMAC partagé, stocké comme secret système (jamais inline ici).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # URL de base du module workflow (endpoint d'ingestion : `{url}/events/{source_id}`).
    workflow_base_url: str = ""
    # UUID de la source, attribué côté workflow à l'enregistrement.
    source_id: str = ""
    # Slug du secret système portant la clé HMAC partagée.
    secret_slug: str = "workflow_events_hmac"
    # Valeur du champ système `_source` (identifie l'application émettrice).
    source_uri: str = "urn:yoops:devpod"
    # Liste blanche des types d'events relayés (vide = aucun relais, même si enabled).
    # L'intersection avec le registre réel est refaite à l'abonnement (défensif).
    events: list[str] = Field(default_factory=list)


class ListmonkConfig(BaseModel):
    """Connexion à l'instance Listmonk (emails du cycle d'abonnement).

    Même motif que `EventsProducerConfig` : `enabled`, une URL de base, et un
    `apikey_secret` qui RÉFÉRENCE un secret système — jamais la valeur. Le
    secret porte la paire `api_user:token` telle que l'API Listmonk l'attend
    (`Authorization: token api_user:token`, relevé dans la doc officielle —
    l'instance déployée devra le confirmer).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: URL de base de l'instance (ex. https://listmonk.yoops.org).
    url: str = ""
    #: Slug du secret système portant `api_user:token`. Une RÉFÉRENCE, jamais la clef.
    apikey_secret: str = ""


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    server: ServerConfig
    auth: AuthConfig
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    devpod: DevpodConfig = Field(default_factory=DevpodConfig)
    hosts: list[HostConfig] = Field(default_factory=list)
    hypervisor_types: list[HypervisorType] = Field(default_factory=list)
    hypervisors: list[Hypervisor] = Field(default_factory=list)
    caddy: CaddyConfig = Field(default_factory=CaddyConfig)
    cloudflare_manager: CloudflareManagerConfig = Field(default_factory=CloudflareManagerConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    events_producer: EventsProducerConfig = Field(default_factory=EventsProducerConfig)
    listmonk: ListmonkConfig = Field(default_factory=ListmonkConfig)
    bastion: BastionConfig = Field(default_factory=BastionConfig)
    # Reglages de facturation : la politique de relance d'un prelevement refuse
    # vaut pour l'installation entiere, pas pour un abonne — elle est donc ici
    # et non en base. Modele defini dans `portal.billing.config`, qui n'importe
    # rien du portail (pas de cycle).
    billing: BillingConfig = Field(default_factory=BillingConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_proxmox_nodes(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "proxmox_nodes" in data and "hypervisors" not in data:
            nodes = data.pop("proxmox_nodes")
            migrated = []
            for n in nodes or []:
                if isinstance(n, dict):
                    n = {k: v for k, v in n.items() if k != "script_url"}
                migrated.append(n)
            data["hypervisors"] = migrated
        return data


class HostProfile(BaseModel):
    """Profil de host : ce qu'un forfait provisionne.

    Trois niveaux, chacun avec sa responsabilité :

    - le **type d'hyperviseur** déclare les variables qui existent ;
    - le **profil de machine** fige les paramètres du script de création (RAM,
      disque, gabarit) et porte le type ;
    - le **profil de host** choisit un profil de machine et VALUE ses variables
      — dont `capacity_workspaces`, le nombre de workspaces que la machine
      supporte sans planter.

    Le profil de machine sait construire la VM ; il ne sait pas ce qu'elle vaut
    à l'usage. C'est l'exploitant qui le dit, ici, une fois pour toutes.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    label: str
    #: Slug du profil de machine — c'est lui qui porte le type d'hyperviseur,
    #: donc la liste des variables à renseigner.
    machine_profile: str
    #: Slug de variable → valeur. Stockées en texte comme `MachineProfile.params` :
    #: la déclaration porte le type, la valeur reste ce que l'admin a saisi.
    variables: dict[str, str] = Field(default_factory=dict)

    def capacity_workspaces(self) -> int | None:
        """Capacité déclarée, ou `None` si le profil ne la renseigne pas.

        `None` n'est pas « illimité » par indulgence : c'est « non renseigné ».
        L'appelant décide s'il refuse ou s'il laisse passer — mais il le décide
        en connaissance de cause.
        """
        brut = self.variables.get(CAPACITY_VARIABLE, "").strip()
        if not brut:
            return None
        try:
            return int(brut)
        except ValueError:
            return None


class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


_WORKSPACE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


class UserDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "4h"


class HarpocrateUserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""


class GitCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    kind: Literal["ssh", "token"]
    key_path: str = ""
    username: str = ""
    token: str = ""


class WorkspaceExpose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = ""


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    branch: str = ""
    git_credential: str = ""


class WorkspaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    template: str = ""
    devcontainer_path: str = ""
    recipes: list[str] = Field(default_factory=list)
    ide: str = ""
    idle_timeout: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    expose: WorkspaceExpose = Field(default_factory=WorkspaceExpose)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    ssh_key: bool = False
    profile: ProfileRef | None = None
    start_recipes: list[str] = Field(default_factory=list)
    default_start: str = ""
    recipe_volumes: list[str] = Field(default_factory=list)
    init_recipes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    # Spec 35 : types d'agents à configurer dans le workspace (accès direct MCP).
    agents: list[str] = Field(default_factory=list)
    # Épingle « garder actif » (enabler 6016436b) : exempte le workspace de toute
    # suggestion d'arrêt pour inactivité, quel que soit son idle.
    keep_active: bool = False
    # Surcharge ponctuelle de la limite mémoire du conteneur (enabler 59864c37) :
    # "" = hériter de devpod.defaults.memory_limit.
    memory_limit: str = ""

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_limit(cls, v: str) -> str:
        return _validate_memory_limit(v)

    @field_validator("agents")
    @classmethod
    def validate_agent_ids(cls, v: list[str]) -> list[str]:
        from portal.agents.models import AGENT_ID_RE

        for aid in v:
            if not AGENT_ID_RE.fullmatch(aid):
                raise ValueError(
                    f"agent id {aid!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
                )
        return v

    @field_validator("start_recipes", "init_recipes")
    @classmethod
    def validate_recipe_ids(cls, v: list[str]) -> list[str]:
        from portal.recipes.models import _RECIPE_ID_RE

        for rid in v:
            if not _RECIPE_ID_RE.fullmatch(rid):
                raise ValueError(
                    f"recipe id {rid!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
                )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _WORKSPACE_NAME_RE.fullmatch(v):
            raise ValueError(f"name '{v}' must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v and v.startswith("-"):
            raise ValueError("source must not start with '-' (argument injection prevention)")
        return v


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    secret_ns: str
    culture: str = "fr"
    defaults: UserDefaults = Field(default_factory=UserDefaults)
    harpocrate: HarpocrateUserConfig = Field(default_factory=HarpocrateUserConfig)
    git_credentials: list[GitCredential] = Field(default_factory=list)
    workspaces: list[WorkspaceSpec] = Field(default_factory=list)

    @field_validator("secret_ns")
    @classmethod
    def validate_secret_ns(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"secret_ns must be a valid UUID, got: {v!r}") from e
        return str(uuid.UUID(v))
