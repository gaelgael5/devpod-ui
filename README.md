# Workspace Portal — Spec corpus

> Nom de travail : **workspace-portal** (à renommer si besoin). Domaine : `dev.yoops.org`.
> Projet **indépendant** d'ag.flow et d'ag.flow.docker (aucun couplage runtime ni de source ; voir `01_ARCHITECTURE.md` §Décisions).

## Objectif

Un portail web self-hosted qui remplace l'usage local de DevPod desktop. L'utilisateur se
connecte (OIDC Keycloak), paramètre des environnements de travail (devcontainers), et obtient un
VS Code dans le navigateur — **sans rien installer sur son poste**. L'orchestration tourne dans un
conteneur sur l'infra ; les workspaces sont des conteneurs Docker provisionnés sur un ou plusieurs
nœuds Docker distants, pilotés via DevPod CLI en mTLS.

## Principes non négociables

1. **Pas de base de données.** L'état vit dans des fichiers YAML sous `/data` (volume monté).
   Backup = `tar` d'un répertoire. Voir les limites dans `03_PITFALLS.md` §Backup.
2. **Aucun secret dans une image Docker** (ni clé TLS, ni clé privée, ni API key). Tout secret
   est généré au runtime ou monté depuis `/data`. C'est la règle qui a guidé toute l'archi.
3. **Isolation utilisateur par répertoire.** `users/<login>/` contient toute la config, les clés
   et l'état DevPod (`DEVPOD_HOME`) d'un utilisateur. Suppression = `rm -rf` du dossier.
4. **Hosts = admin only.** Les utilisateurs ne déclarent pas de nœuds Docker.
5. **Secrets multi-utilisateurs = un coffre, un namespace par user** (GUID `secret_ns`).
   Isolation applicative imposée par le portail (voir `03_PITFALLS.md` §Secrets).
6. **Formats standards** (devcontainer.json, devcontainer Features) pour rester portable même si
   DevPod change de mainteneur.

## Comment Claude Code doit utiliser ce corpus

- Lire **`04_CLAUDE.md` en premier** (règles d'autonomie, conventions, definition of done).
- Puis `01_ARCHITECTURE.md`, `02_CONFIG_REFERENCE.md`, `03_PITFALLS.md` (contexte transversal).
- Exécuter les milestones **dans l'ordre** `10_M1` → `16_M7`. Chaque milestone est livrable et
  testable indépendamment. Ne pas démarrer un milestone sans avoir validé la DoD du précédent.
- **Avant tout appel à `devpod`, lancer `devpod version` et `devpod up --help`** : les flags de la
  CLI dérivent entre versions ; ce corpus indique l'intention, pas un contrat de flags figé.

## Ordre des milestones

| # | Fichier | Contenu | Dépend de |
|---|---------|---------|-----------|
| M1 | `10_M1_foundation.md` | Squelette projet, modèles config (pydantic), résolveur de secrets | — |
| M2 | `11_M2_api_auth.md` | FastAPI, OIDC Keycloak, provisioning répertoire user, RBAC | M1 |
| M3 | `12_M3_devpod_wrapper.md` | Wrapper DevPod (subprocess async, DEVPOD_HOME par user, lifecycle) | M1, M2 |
| M4 | `13_M4_node_enrollment.md` | Enrôlement nœud : signature CSR, install-node.sh, join token, Docker mTLS | M1, M2 |
| M5 | `14_M5_install_portal.md` | install.sh portail : init CA, premier config, image + docker compose | M1→M4 |
| M6 | `15_M6_exposure.md` | Exposition workspace : cloudflare-manager + routes Caddy dynamiques | M3, M5 |
| M7 | `16_M7_recipes.md` | Registre de recettes (Features), 1er lot extrait des 7 Dockerfiles | M3 |

## Stack imposée

- Python 3.12, FastAPI, `pydantic` v2 + `pydantic-settings`, `authlib` (OIDC), `httpx`, `pyyaml`,
  `uvicorn`. Tests : `pytest` + `pytest-asyncio`.
- DevPod CLI (binaire dans l'image, provider `docker` et `ssh`).
- Caddy (reverse proxy + TLS wildcard). Cloudflare Tunnel via `cloudflare-manager` existant.
- Keycloak (`security.yoops.org`, realm `yoops`) — déjà déployé.
- Harpocrate (`harpocrate.yoops.org`) — backend secrets optionnel, fallback inline.
