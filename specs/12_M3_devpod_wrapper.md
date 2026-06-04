# M3 — Wrapper DevPod (lifecycle des workspaces)

**Objectif :** lancer/arrêter/supprimer des workspaces via la CLI DevPod, en isolant chaque user par
`DEVPOD_HOME`, en pilotant un daemon Docker distant en mTLS, sans bloquer l'event loop.

## Prérequis
- M1, M2 livrés. DevPod CLI dans l'image (sera packagé en M5 ; en dev, installé localement).
- Un nœud Docker mTLS accessible (sera automatisé en M4 ; en dev, un daemon local en TLS suffit).

## Étape préalable IMPÉRATIVE
Exécuter et lire :
```
devpod version
devpod up --help
devpod list --help
devpod provider --help
```
Adapter les flags ci-dessous à la version réelle. Signaler tout écart. Piège §B-7.

## Étapes

### M3.1 — Environnement d'appel (`devpod/env.py`)
- Construire l'environnement de chaque subprocess :
  - `DEVPOD_HOME=<safe_user_path(login,"devpod")>` (créé si absent). Piège §B-8.
  - Pour un host `docker-tls` : `DOCKER_HOST=tcp://...:2376`, `DOCKER_TLS_VERIFY=1`,
    `DOCKER_CERT_PATH=<global.devpod.client_cert_path>` (contient `ca.pem`/`cert.pem`/`key.pem`).
    Pièges §A-4, §A-2.
  - Pour un host `ssh` : pas de DOCKER_*, le provider ssh gère la connexion.

### M3.2 — Initialisation du provider par DEVPOD_HOME (`devpod/provider.py`)
- Comme l'état est isolé par user, s'assurer que le provider voulu existe dans ce `DEVPOD_HOME`
  (`devpod provider list --output json` → sinon `devpod provider add docker` / `ssh`). Piège §B-9.
- Idempotent.

### M3.3 — Runner async (`devpod/runner.py`)
- `asyncio.create_subprocess_exec(...)`, capture stdout/stderr **streamés** vers
  `logs/<login>/<ws_id>.log`. Jamais de `subprocess.run` bloquant. Piège §B-10, §C-15.
- Verrou par `ws_id` (`asyncio.Lock` enregistré dans un dict, ou lockfile). Piège §C-20.

### M3.4 — Opérations (`devpod/service.py`)
- `up(login, ws_spec)` :
  1. Résoudre les secrets de `ws_spec.env` (scope user) → dict d'env runtime (type `Secret`).
  2. Générer le `devcontainer.json` effectif (template + recipes + overrides) dans un fichier
     temporaire sous le dossier user (la génération complète des recipes est en M7 ; ici, gérer
     template + env).
  3. `ws_id = f"{login}-{ws_spec.name}"` (re-valider DNS-safe). Piège §B-13, §C-18.
  4. Lancer en tâche de fond : `devpod up <source> --id <ws_id> --ide openvscode
     --devcontainer-path <gen> [flag pour NE PAS auto-ouvrir l'IDE]`. Injecter les secrets via
     l'environnement du process / `--devcontainer-... ` runtime, **jamais en build arg**. Piège §D-21.
  5. Écrire un statut (`provisioning|running|failed`) dans `routes/<ws_id>.json`.
- `stop(login, ws_id)`, `delete(login, ws_id)`, `status(login, ws_id)`, `list(login)`
  (`devpod list --output json` filtré par DEVPOD_HOME).
- **Récupération du port** : voir M6. En M3, exposer un hook `get_port(ws_id)` qui sera implémenté
  proprement en M6 ; ne pas se reposer sur un parsing fragile maintenant. Piège §B-12.

### M3.5 — Endpoints
- `POST /me/workspaces/{name}/up` → 202 + `ws_id` (async). `/stop`, `/delete`, `/status`.
- Le `host` demandé doit exister dans `hosts` global ET être autorisé pour le user (sinon 403).

## Tests
- `env.py` : bons DOCKER_* selon type de host ; DEVPOD_HOME pointe dans le dossier user.
- Runner : un faux binaire `devpod` (script qui dort + écrit sur stdout) prouve le streaming non
  bloquant et l'écriture des logs.
- Verrou : deux `up` concurrents sur le même `ws_id` → le second attend/refuse. Piège §C-20.
- `up` rejette un `name` non DNS-safe avant tout lancement.
- Secrets : vérifier qu'aucun secret n'apparaît dans `logs/` (grep sur la valeur de test).

## Definition of Done
- DoD commune + tests verts + un `up` réel réussi sur un nœud de test, IDE atteignable en local
  (port forward manuel acceptable à ce stade — l'exposition propre est M6).

## Pièges spécifiques M3
- §B-7 (flags), §B-8/9 (DEVPOD_HOME + provider par home), §B-10 (non bloquant), §B-12 (port),
  §B-13 (--id namespacé), §C-15 (async), §C-20 (verrou), §D-21 (pas de secret en build arg),
  §A-4/2 (mTLS + SAN).
- Piège subtil : un `devpod up` qui échoue peut laisser un conteneur orphelin. Prévoir un nettoyage
  (`devpod delete <ws_id> --force`) dans le chemin d'erreur, et une réconciliation au démarrage.
