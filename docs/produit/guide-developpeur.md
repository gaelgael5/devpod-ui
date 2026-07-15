# Guide développeur

Pour contribuer au portail. Conventions, layout, tests et workflow.

## Stack

- **Backend** : Python 3.12, FastAPI, pydantic v2 / pydantic-settings, authlib,
  httpx, SQLAlchemy async (asyncpg) + Alembic, structlog, pytest.
- **Frontend** : Vite, React 18, TypeScript strict, TanStack Query, zustand,
  react-router-dom, Tailwind, shadcn/ui, i18next, Vitest + Testing Library + MSW,
  xterm.js.
- **e2e** : Playwright (contre la stack déployée, navigateur Browserless distant).

## Layout du code

```
backend/src/portal/
  app.py            FastAPI app + lifespan (montage des routeurs)
  settings.py       AppSettings (env)
  config/           modèles pydantic, store YAML (/data), safe_user_path
  db/               tables SQLAlchemy, accès (skills, delegations, test_hosts…)
  auth/             OIDC, sessions, RBAC (sub anchoring)
  secrets/          résolveur, backends harpocrate + inline, vault
  devpod/           env builder, runner, vm_init, test_host_share, exec
  exposure/         client Caddy admin, cloudflare, registre routes/ports
  events/           registre EVENT_TYPES, schemas (CloudEvents), bus
  mcp/              serveur MCP + devpod_tools (registry + _IMPLS)
  routes/           handlers REST (/me, /admin, /auth, compose, test_vm…)
  compose/          service compose (deploy, host_exec, list_host_stacks)
backend/alembic/    migrations
frontend/src/
  features/         par domaine (workspaces, skills, compose, auth, vault…)
  shared/           layouts (AppShell, guards), api client
  i18n/             fr.json / en.json
  router.tsx        routes
  e2e/              Playwright (harness, specs, fixtures)
```

## Conventions

### Python
- `async/await` partout — **jamais** de `subprocess.run` bloquant dans un handler
  (exception assumée : DevPod CLI via `asyncio.create_subprocess_exec`).
- pydantic v2, `extra="forbid"` sur tous les modèles.
- Logs via `structlog.get_logger(__name__)` — **jamais** `print()` ; les secrets
  ne se déballent que par `.reveal()` au point d'injection.
- `from __future__ import annotations`, type hints partout ; fichiers ≤ 300 lignes.
- Tout chemin sous `/data` passe par `safe_user_path` (regex + `is_relative_to`).

### Sécurité (non négociable)
- Aucun secret en build arg, `ENV` Dockerfile, layer, log, ou repo.
- Aucun daemon Docker piloté sans `tlsverify` ; SAN = IP/hostname exacts.
- Join tokens : usage unique, hashés, TTL court ; CSR validées avant signature.
- Entrées utilisateur (login, workspace, recipe id) : validation regex stricte
  avant tout usage en chemin, `--id` ou hostname.

### Frontend
- TypeScript strict ; TanStack Query pour l'état serveur.
- i18n obligatoire (fr/en) — pas de chaîne en dur.
- Vitest + Testing Library ; `describe`/`it`.

## Tests

```bash
# Backend
cd backend && uv run pytest -v
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
# Frontend
cd frontend && npm run test        # vitest
cd frontend && npx tsc --noEmit && npx eslint .
# e2e (contre la stack déployée)
cd frontend && npm run e2e         # variables E2E_BASE_URL, E2E_CDP_URL, E2E_WS…
```

**TDD** : test rouge → impl → test vert → commit. Les cas de rejet sécurité
(path traversal, isolation `secret_ns`, token réutilisé) sont des **tests**.

> Astuce : ajouter un type d'événement impose 3 synchronisations
> (`events/models.py` `EVENT_TYPES`, `events/schemas.py` `dataSchema`, et les
> tests figés `tests/events/` + `tests/routes/test_event_schemas.py`, à dériver
> d'`EVENT_TYPES`). L'oubli du `dataSchema` fait **crasher le portail à l'import**.

## Workflow Git

- Tout le code sur la branche **`dev`** (jamais `feat/*`, jamais `main`
  directement). Vérifier `git branch --show-current` avant d'éditer.
- Commits en **français**, format conventionnel (`feat:`, `fix:`, `chore:`,
  `docs:`, `test:`…).
- Ne jamais livrer (test/git) sans demande explicite ; relire `git diff` sous
  l'angle « aucun secret ».

## Déploiement de test

Cycle : lint + mypy → push `dev` → `dev-deploy.sh` sur test1 → lire les vrais logs
→ tester via Browserless/curl. **Ne pas** simuler l'environnement avec
`docker run --rm python -c '...'` (contexte lifespan différent → faux positifs).
Voir [Installation & exploitation](installation-exploitation.md).
