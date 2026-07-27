# Tests e2e (Playwright)

Suite d'acceptation end-to-end du portail. Contrairement aux tests Vitest
(composants isolés, MSW), ces tests pilotent un **navigateur réel** contre la
**stack déployée** (backend + front build). Ils automatisent les ATDD du backlog.

## Modèle d'exécution

- **Cible** : le portail complet déployé sur `test1` (`http://<ip>:8080`).
- **Navigateur** : Chromium distant (Browserless sur `test1:3000`), connecté en
  CDP. À défaut d'endpoint distant, un Chromium local est lancé.
- **Auth** : `auth.setup.ts` établit une session admin via `POST /auth/local-login`
  (dev, `dev_mode` + `allow_local_auth`) et la sérialise dans `e2e/.auth/state.json`.
  Tous les scénarios rechargent cette session — pas de pilotage Keycloak headless.

Rien n'est codé en dur : l'IP de `test1` étant éphémère, tout passe par des
variables d'environnement.

## Variables d'environnement

| Variable | Rôle | Exemple |
|----------|------|---------|
| `E2E_BASE_URL` | URL du portail déployé | `http://192.168.10.196:8080` |
| `E2E_CDP_URL` | endpoint CDP du Chromium distant (Browserless) ; absent ⇒ Chromium local | `http://192.168.10.196:3000` |
| `E2E_LOCAL_USER` | identifiant local-login | `gaelgael5` |
| `E2E_LOCAL_PASSWORD` | mot de passe local-login | — |

## Lancer

```bash
cd frontend

# Lister les scénarios (hors ligne, ne lance aucun navigateur)
npm run e2e:list

# Lancer contre test1 (navigateur distant Browserless)
E2E_BASE_URL=http://192.168.10.196:8080 \
E2E_CDP_URL=http://192.168.10.196:3000 \
E2E_LOCAL_USER=<user> E2E_LOCAL_PASSWORD=<pass> \
npm run e2e

# Développer les specs avec un Chromium local (E2E_CDP_URL omis)
#   npx playwright install chromium   # une fois
E2E_BASE_URL=http://192.168.10.196:8080 \
E2E_LOCAL_USER=<user> E2E_LOCAL_PASSWORD=<pass> \
npm run e2e
```

> L'endpoint CDP exact de l'instance Browserless doit être confirmé contre la VM
> (le chemin dépend de la version du serveur) ; il est isolé dans `E2E_CDP_URL`.

## Organisation

- `playwright.config.ts` — projets `setup` (auth) → `chromium` (scénarios).
- `fixtures.ts` — navigateur distant (CDP) + contexte porteur de la session.
- `auth.setup.ts` — login local → storageState réutilisable.
- `helpers.ts` — navigation, seeding d'état via l'API du portail.
- `*.spec.ts` — un fichier par ATDD (parcours UI).
- `api/*.spec.ts` — ATDD de niveau intégration (routage gateway, délégation,
  ancrage sub) pilotés au niveau API via `request`.
