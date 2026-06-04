# 01 — Architecture

## Vue d'ensemble

```
                          Navigateur (zéro install poste)
                                     │  HTTPS (OIDC)
                                     ▼
   Cloudflare Tunnel ──► Caddy (reverse proxy + authforward) ──► Portail FastAPI
        (cloudflare-manager crée les hostnames dynamiques)            │
                                                                      │ subprocess
                                                                      ▼
                                                              DevPod CLI (dans l'image)
                                                                      │ DOCKER_HOST mTLS
                          ┌───────────────────────────────────────────┼─────────────┐
                          ▼                                            ▼             ▼
                  Nœud Docker "local"                          Nœud "pve1"     Nœud "..."
                  (daemon TCP:2376 + TLS)                      (TCP:2376/TLS)
                  ┌─────────┬─────────┐
                  │ ws cont.│ ws cont.│  ← chaque workspace = 1 conteneur
                  │ openvscode-server │     openvscode-server bind un port
                  └─────────┴─────────┘
```

Le portail est **stateless au sens applicatif** : tout son état persistant est dans `/data`
(volume). L'image est jetable et reconstructible. Les workspaces vivent dans les daemons Docker
des nœuds, pas dans le portail.

## Composants

### Portail (conteneur unique)
- **FastAPI** : auth OIDC, UI/endpoints de paramétrage, RBAC, orchestration.
- **DevPod CLI** : binaire embarqué dans l'image. Appelé en subprocess, un `DEVPOD_HOME` par user.
- **Résolveur de secrets** : Harpocrate (API key globale) ou inline (`secrets.yaml`), namespacé par user.
- **Caddy** : peut tourner dans le même conteneur ou à côté. Recommandé : conteneur séparé dans le
  même `docker compose`, route configurée via l'API admin de Caddy par le portail (voir M6).

### Nœuds Docker (slaves)
- Rien de propriétaire : juste `dockerd` exposé en `tcp://0.0.0.0:2376` avec `tlsverify`.
- Enrôlés via CSR signée par la CA du portail (M4). Aucun agent permanent du portail dessus :
  DevPod injecte lui-même son agent dans les conteneurs au moment du `up`.

## Layout `/data` (source de vérité unique)

```
/data/
├── config.yaml                 # GLOBAL (admin) : server, auth, hosts, devpod defaults, secrets.backend
├── .env                        # HARPOCRATE_API_KEY, OIDC_CLIENT_SECRET (perms 600, jamais dans l'image)
├── certs/
│   ├── ca/                     # ca.pem + ca-key.pem (RACINE DE CONFIANCE — voir pièges)
│   ├── portal/                 # cert CLIENT du portail (signé par CA) pour piloter les daemons
│   └── nodes/<node>/           # cert serveur signé pour chaque nœud (copie de suivi)
├── templates/                  # devcontainer.json partagés (admin), lecture seule côté user
├── recipes/                    # Features partagées (admin) — registre PROPRE au portail
├── routes/                     # mapping workspace→port→hostname (fichier, pas de DB)
├── logs/
└── users/
    └── <login>/
        ├── config.yaml         # SES workspaces, SES git_credentials, secret_ns, defaults perso
        ├── secrets.yaml        # uniquement si backend inline (perms 600)
        ├── keys/{git,workspaces}/
        ├── recipes/            # Features perso
        ├── templates/          # templates perso
        └── devpod/             # DEVPOD_HOME dédié (état DevPod isolé)
```

## Flux : provisionner un workspace

1. User authentifié POST `/workspaces` avec `{name, source, template|devcontainer_path, recipes[], host?, env}`.
2. Portail **sanitize** `name` (DNS-safe, voir pièges) → `ws_id = "<login>-<name>"`.
3. Résout les secrets (`${vault://...}` relatifs au `secret_ns` du user) → env runtime (jamais build arg).
4. Génère un `devcontainer.json` effectif : template + recipes (clé `features`) + overrides.
5. Lance en tâche de fond : `DEVPOD_HOME=users/<login>/devpod DOCKER_HOST=tcp://… DOCKER_TLS_VERIFY=1 DOCKER_CERT_PATH=certs/portal devpod up <source> --id <ws_id> --ide openvscode --devcontainer-path <gen> [--open-ide=false]`.
6. Récupère le port openvscode (parsing JSON / inspection — voir M3/M6).
7. Alloue `ws-<login>-<name>.dev.yoops.org`, met à jour `routes/`, pousse la route Caddy + crée le hostname via cloudflare-manager.
8. Le navigateur accède à l'URL ; Caddy valide l'OIDC avant de proxifier vers openvscode (qui n'a **aucune** auth propre).

## Modèle de rôles (Keycloak realm `yoops`)
- `dev` : voit/édite son répertoire, provisionne sur les hosts autorisés.
- `admin` : + gère `hosts`, `templates`/`recipes` partagés, enrôlement nœuds, voit tous les users.

## Décisions (journal — ne pas réouvrir sans raison)

| Décision | Choix | Raison |
|---|---|---|
| Orchestrateur | DevPod CLI (pas Coder) | Coder jugé trop lourd / instable par l'owner |
| Provider workspaces | `docker` (mTLS) + `ssh` en repli | Conteneurs, pas de VM par workspace |
| Nouvelle VM par nœud ? | Non | Provider docker = conteneurs sur le daemon existant |
| Persistance | Fichiers YAML, pas de DB | Backup/restore triviaux |
| Secret dans image | Interdit | Layers extractibles ; casse le restore |
| Isolation user | 1 répertoire + 1 DEVPOD_HOME | Suppression/backup par user, isolation structurelle |
| Hosts | Admin only | Contrôle de capacité |
| Multi-secrets | 1 coffre + namespace GUID | Vault/user = trop lourd ; path-prefix suffit |
| Registre recipes | Propre au portail, format Feature standard | Pas de couplage à ag.flow.docker, mais artefacts interchangeables |
| TLS vs SSH nœud | mTLS (SSH en repli documenté) | Surface limitée à l'API Docker, révocation par cert |
