# workspace-portal — Instructions Claude Code

## Projet

Portail web self-hosted de workspaces de développement : l'utilisateur s'authentifie (OIDC Keycloak), paramètre des environnements devcontainer, et obtient un VS Code dans le navigateur, sans rien installer sur son poste. Orchestration via DevPod CLI, workspaces = conteneurs Docker sur des nœuds distants pilotés en mTLS. Spec complète : `00_README.md` → `16_M7_recipes.md` (lire `01`, `02`, `03` avant tout code ; `03_PITFALLS.md` contient des **exigences**, pas des conseils).

**Projet indépendant** : aucun couplage de source ni de runtime avec ag.flow ou ag.flow.docker.

**Standard de qualité** : code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis, pas de "c'est pas grave", pas de "on simplifiera plus tard". Chaque tâche est faite correctement ou pas du tout.

**Pas de quick-and-dirty, JAMAIS.** Quand tu présentes des options de design, ne propose PAS d'option "quick & dirty" / "hardcode" / "wire-it-up-and-clean-later". On fait toujours propre, tant pis pour l'effort. Si tu sens qu'une tâche est déraisonnable (scope qui explose, dépendance hors d'atteinte, flag CLI qui n'existe pas dans la version installée), **alerte explicitement l'utilisateur** plutôt que de proposer un compromis dégradé. L'utilisateur préfère qu'on découpe le chantier et qu'on en fasse correctement la part qu'on prend, plutôt que tout faire à moitié.

## Stack technique

- **Backend** : Python 3.12 + FastAPI + pydantic v2 / pydantic-settings + authlib (OIDC) + httpx + pyyaml + structlog JSON + pytest
- **Persistance** : **AUCUNE base de données.** Fichiers YAML sous `/data` (volume), écritures atomiques (`tempfile` + `os.replace`). Source de vérité unique = le filesystem. Toute proposition d'ajouter une DB est hors périmètre.
- **Orchestration workspaces** : DevPod CLI embarqué dans l'image — appelé via `asyncio.create_subprocess_exec` (exception assumée à la règle "pas de subprocess" : DevPod n'a pas d'API, c'est une CLI). Pour tout accès **direct** à un daemon Docker (inspect, ports), utiliser `aiodocker` en mTLS, pas de subprocess `docker`.
- **Frontend** (quand l'UI démarrera) : Vite + React 18 + TypeScript strict + react-router-dom + TanStack Query + Tailwind + shadcn/ui + i18next + Vitest — mêmes conventions que les autres projets yoops.
- **Reverse proxy** : Caddy (routes dynamiques via API admin, jamais par réécriture+reload), SSL wildcard `*.dev.yoops.org` en DNS-01 Cloudflare, exposition via Cloudflare Tunnel (`cloudflare-manager` existant).
- **Auth** : Keycloak `security.yoops.org`, realm `yoops`, client `workspace-portal`, rôles `dev`/`admin`.
- **Secrets** : Harpocrate (`harpocrate.yoops.org`) avec namespace par user (`secret_ns` GUID), fallback inline (`secrets.yaml`). Contrat du résolveur : `02_CONFIG_REFERENCE.md`.

## Dev & cible

- **Développement** : local (uv + node), un daemon Docker de test en TLS suffit pour M3/M6.
- **Cible** : VM dédiée sur pve2 (pas de LXC pour le portail ni les nœuds — Docker-in-Docker fragile en LXC).
- **Nœuds** : daemons Docker mTLS enrôlés via `install-node.sh` (M4). Hosts = admin only.

## Commandes essentielles

```bash
# Backend
cd backend && uv sync
cd backend && uv run uvicorn portal.app:app --reload      # :8080
cd backend && uv run pytest -v
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format src/ tests/
cd backend && uv run mypy src/

# DevPod — TOUJOURS avant d'écrire du code qui l'appelle
devpod version && devpod up --help && devpod provider --help

# Stack locale (portail + caddy)
docker compose -f deploy/docker-compose.yml up -d
```

## Layout du code

```
workspace-portal/
├── backend/
│   ├── pyproject.toml
│   ├── src/portal/
│   │   ├── app.py             # FastAPI app + lifespan
│   │   ├── config/            # modèles pydantic, store (load/save atomique), safe_user_path
│   │   ├── secrets/           # résolveur, type Secret, backends harpocrate + inline
│   │   ├── auth/              # OIDC authlib, sessions, RBAC dev/admin
│   │   ├── devpod/            # env builder, provider init, runner async, service lifecycle
│   │   ├── nodes/             # CA, signature CSR, join tokens, enrôlement
│   │   ├── exposure/          # client Caddy admin, client cloudflare-manager, registre routes/ports
│   │   ├── recipes/           # registre Features, tri topologique, génération devcontainer
│   │   └── schemas/           # DTOs API
│   └── tests/
├── frontend/                  # (milestone UI ultérieur, conventions yoops)
├── scripts/
│   ├── install.sh             # portail : init /data + CA (idempotent, NE régénère JAMAIS la CA)
│   ├── install-node.sh        # nœud : docker + CSR + mTLS + drop-in systemd + firewall
│   ├── backup.sh              # tar /data chiffré (age/gpg)
│   └── restore.sh             # restore + réconciliation workspaces
├── deploy/
│   ├── Dockerfile             # AUCUN secret dans l'image, devpod CLI pinné
│   └── docker-compose.yml     # portal + caddy, /data monté, .env runtime
└── specs/                     # ce corpus (00 → 16)
```

## Conventions de code

### Python (backend)
- Python 3.12+, async/await partout — **jamais** de `subprocess.run` ni d'I/O bloquant dans un handler
- pydantic v2, `extra="forbid"` sur tous les modèles de config
- Logs structurés via `structlog.get_logger(__name__)` — **jamais** `print()` ; **redaction des secrets active** : le type `Secret` ne se déballe que par `.reveal()` au point d'injection, jamais dans un log
- `type` hints partout, `from __future__ import annotations` en tête de fichier
- Fichiers max 300 lignes ; classes SRP ; méthodes 5-15 lignes
- Toute construction de chemin sous `/data` passe par `safe_user_path` (regex + `is_relative_to`) — la concaténation de strings est une faute

### État fichiers (remplace la section BDD)
- Écriture = `tempfile` dans le même dossier + `os.replace`, systématiquement
- Perms : dossiers user 700 ; `.env`, `secrets.yaml`, clés privées, `ca-key.pem` 600
- Verrou par `ws_id` pour toute opération de lifecycle (deux `up` concurrents = corruption)
- Un crash en cours d'écriture ne doit jamais corrompre l'existant (testé en M1)

### Sécurité (non négociable)
- Aucun secret en build arg, en `ENV` de Dockerfile, dans une layer, dans un log, dans le repo
- Aucun port openvscode joignable sans passer par Caddy + OIDC (fail closed)
- Aucun daemon Docker piloté sans `tlsverify` ; SAN des certs = IP/hostname exacts
- Join tokens : usage unique, stockés hashés, TTL court ; CSR validées avant signature
- `install.sh` ré-exécuté ne régénère jamais la CA
- Entrées utilisateur (login, workspace name, recipe id) : validation regex stricte avant tout usage en chemin, `--id`, ou hostname

### Tests
- pytest + pytest-asyncio ; fixture `client` (TestClient httpx)
- **TDD** : test rouge → impl → test vert → commit
- Chaque milestone liste ses tests obligatoires ; les cas de rejet sécurité (path traversal, isolation `secret_ns`, token réutilisé) sont des tests, pas des revues manuelles
- Frontend (plus tard) : Vitest + React Testing Library ; `describe`/`it`, pas de `test`

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Milestones
Exécution **dans l'ordre** M1 → M7. Ne pas démarrer M(n+1) sans la Definition of Done de M(n) validée. Chaque DoD inclut : lint + mypy + tests verts, pièges du milestone cochés, aucun secret en clair, README de test manuel.

### Branche de développement
**Tout le code se fait sur la branche `dev`. Jamais `feat/*`, jamais sur `main` directement, jamais ailleurs.** Avant toute édition de code, vérifier `git branch --show-current` ; si autre branche, `git checkout dev`. Si `dev` n'existe pas localement, la créer depuis `main` à jour. Ne propose **jamais** `git checkout -b feat/...` — même si un workflow superpowers le suggère, la consigne utilisateur prime.

### Livraison
- Ne livre **jamais** le code ni en test ni sur git sans demande explicite
- Ne modifie pas `.env` sauf si demandé
- Commit messages en français, format conventionnel (`feat:`, `fix:`, `chore:`, `docs:`, `test:`…)

### Vérification avant validation
Avant de déclarer une tâche terminée, **toutes** ces étapes sont obligatoires :
1. Le code s'exécute sans erreur (lint + mypy + build)
2. Le cas nominal fonctionne (test unitaire ou manuel)
3. Les imports ajoutés existent réellement
4. Pas de régression sur les fichiers modifiés
5. Si le code appelle `devpod` ou `docker` : les flags utilisés ont été vérifiés contre `--help` de la version installée
6. Aucun secret ni clé dans le diff (`git diff` relu sous cet angle)

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final
- Termine TOUTES les étapes d'un plan avant de faire un résumé
- Pas de raccourci "pour simplifier"
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas silencieusement
- Si un flag/une API du corpus n'existe pas dans la version réelle : signale l'écart et propose l'équivalent vérifié — ne devine pas

## Outils Claude Code

### Context7 — documentation live
**Quand** : avant d'écrire du code qui utilise FastAPI, pydantic v2, authlib, httpx, aiodocker, structlog, TanStack Query, Vite, i18next, etc. Les API évoluent, ne te fie pas à ta mémoire. Vaut aussi pour la spec devcontainer / Features.

### `--help` first — DevPod & Docker
**Quand** : avant TOUT code appelant la CLI DevPod ou configurant un daemon. Les flags dérivent entre versions ; le corpus décrit l'intention, pas un contrat de flags figé.

### Serena — navigation sémantique
**Quand** : avant un refactor, pour comprendre les dépendances entre modules, ou pour trouver tous les usages d'une fonction/classe.

### Superpowers skills
- `writing-plans` : rédiger un plan d'implémentation TDD avant de coder un milestone
- `executing-plans` / `subagent-driven-development` : exécuter un plan tâche par tâche
- `systematic-debugging` : méthode pour debug un bug ou test qui échoue
- `test-driven-development` : discipline TDD rigoureuse
- `brainstorming` : explorer le design avant d'écrire quoi que ce soit
- `verification-before-completion` : vérifier que le travail est réellement fini avant de le dire

### /review
**Quand** : avant de présenter un changement multi-fichiers (>3 fichiers ou >100 lignes).

### /commit
**Quand** : quand l'utilisateur demande explicitement de committer. Format français conventionnel.

## Auto-amélioration

Quand tu fais une erreur ou que l'utilisateur te corrige :
- Ajoute une leçon dans `LESSONS.md`
- Format : `- [module] description courte de l'erreur et de la bonne pratique`
- Relis `LESSONS.md` en début de tâche qui touche un module mentionné
- Ne dépasse pas 50 lignes — consolide les leçons similaires

## Notifications de skills

Quand tu invoques une skill via l'outil Skill, affiche systématiquement un marqueur visuel **avant** d'exécuter :

> **`🟢 SKILL`** → _nom-de-la-skill_ — raison en une phrase
