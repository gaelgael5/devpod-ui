# Frontend UI — Design Spec

**Date :** 2026-06-05
**Milestone :** M8 — Interface utilisateur complète

---

## Objectif

Construire l'interface web du portail DevPod : login OIDC, dashboard workspaces (list/create/stop/delete/status), catalogue de recipes, panel admin (hosts + recipes partagées). Aucune page n'existait avant ce milestone — le backend M1-M7 est complet et expose tous les endpoints nécessaires.

---

## Stack (fixé par CLAUDE.md)

- **Build** : Vite + TypeScript strict
- **UI** : React 18 + Tailwind CSS (`darkMode: 'class'`) + shadcn/ui
- **Routing** : react-router-dom v6
- **Serveur state** : TanStack Query v5
- **UI state global** : Zustand
- **i18n** : i18next + i18next-browser-languagedetector
- **Tests** : Vitest + React Testing Library + msw

---

## Architecture

### Approche retenue

Feature-based + Zustand pour l'état UI global.

TanStack Query gère tout l'état serveur (cache, mutations, polling). Zustand gère uniquement l'état UI transversal non lié au serveur : session utilisateur (login + rôles, hydraté depuis `/me`) et préférence de thème (persistée en `localStorage`).

### Structure de fichiers

```
frontend/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── vitest.config.ts
├── tailwind.config.ts
└── src/
    ├── main.tsx                    # Providers root : QueryClient, BrowserRouter, i18n
    ├── router.tsx                  # Routes déclaratives react-router-dom
    │
    ├── features/
    │   ├── auth/
    │   │   ├── AuthCallback.tsx    # /auth/callback — échange code OIDC, hydrate store, redirige
    │   │   ├── useSession.ts       # useQuery GET /me → UserInfo
    │   │   └── RequireAuth.tsx     # Guard : 401 → redirect /auth/login
    │   │
    │   ├── workspaces/
    │   │   ├── WorkspaceList.tsx   # /workspaces — grille de cartes + bouton Nouveau
    │   │   ├── WorkspaceCreate.tsx # /workspaces/new — formulaire complet
    │   │   ├── WorkspaceCard.tsx   # Carte avec status badge + actions contextuelles
    │   │   ├── useWorkspaces.ts    # useQuery GET /me/workspaces (liste statuts)
    │   │   ├── useWorkspaceOps.ts  # useMutation up/stop/delete + polling statut
    │   │   └── types.ts
    │   │
    │   ├── recipes/
    │   │   ├── RecipeCatalog.tsx   # /recipes — grille de toutes les recipes disponibles
    │   │   ├── RecipePicker.tsx    # Chips multi-select réutilisé dans WorkspaceCreate
    │   │   ├── useRecipes.ts       # useQuery GET /recipes + GET /me/recipes (merge, perso écrase partagé à id égal)
    │   │   └── types.ts
    │   │
    │   └── admin/
    │       ├── AdminHosts.tsx      # /admin/hosts — table CRUD hosts
    │       ├── AdminRecipes.tsx    # /admin/recipes — recipes partagées
    │       ├── useHosts.ts
    │       └── useAdminRecipes.ts
    │
    ├── shared/
    │   ├── components/             # Wrappers shadcn/ui (Button, Badge, Dialog, Sonner…)
    │   ├── layouts/
    │   │   ├── AppShell.tsx        # Rail icônes + header fin + <Outlet />
    │   │   └── AdminGuard.tsx      # 403 si rôle != admin
    │   └── api/
    │       └── client.ts           # fetch wrapper : base URL, credentials, 401 → redirect
    │
    ├── store/
    │   ├── user.ts                 # Zustand : { login, roles, setUser, clear }
    │   └── theme.ts                # Zustand : { theme, toggle } + persistance localStorage
    │
    └── i18n/
        ├── index.ts                # Config i18next (detector, fallback 'en')
        ├── en.json                 # Traductions anglaises (langue par défaut)
        └── fr.json                 # Traductions françaises
```

### Routes

| Path | Composant | Garde |
|---|---|---|
| `/` | redirect → `/workspaces` | — |
| `/auth/login` | redirect → `GET /auth/login` backend | aucun |
| `/auth/callback` | `AuthCallback` | aucun |
| `/workspaces` | `WorkspaceList` | `RequireAuth` |
| `/workspaces/new` | `WorkspaceCreate` | `RequireAuth` |
| `/recipes` | `RecipeCatalog` | `RequireAuth` |
| `/admin/hosts` | `AdminHosts` | `RequireAuth` + `AdminGuard` |
| `/admin/recipes` | `AdminRecipes` | `RequireAuth` + `AdminGuard` |

---

## Navigation

**Rail d'icônes fixe** (style VS Code / Linear) : 48 px de large, icônes pour Workspaces et Recipes. Header fin avec logo et avatar utilisateur. L'admin est accessible uniquement via le menu déroulant du profil (avatar en bas du rail), visible uniquement si `roles` contient `'admin'`.

Le menu profil expose :
- Toggle thème (☀️ / 🌙)
- Toggle langue (FR / EN)
- Liens admin (Hosts, Recipes partagées) — si admin
- Déconnexion → `GET /auth/logout`

---

## Workspaces

### Liste (`/workspaces`)

Grille de `WorkspaceCard`. Chaque carte affiche : nom, source Git, badges recipes, badge statut coloré, actions contextuelles selon statut :

| Statut | Actions disponibles |
|---|---|
| `running` | Ouvrir (lien vers l'URL Caddy), Stop |
| `stopped` | Démarrer, Supprimer |
| `provisioning` | Barre de progression, aucune action (désactivées) |
| `failed` | Supprimer, Réessayer |
| `unknown` | Supprimer |

### Création (`/workspaces/new`)

Page dédiée avec breadcrumb `Workspaces › Nouveau`. Champs :
- **Nom** : input texte, validation live `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$`
- **Source Git** : input URL
- **Nœud** : select parmi les hosts disponibles (GET /admin/hosts) — affiché uniquement si l'utilisateur est admin. Les utilisateurs sans rôle admin voient ce champ masqué ; le backend utilise le nœud par défaut (`host: ""`)
- **Recipes** : `RecipePicker` — chips togglables, une par recipe disponible

Soumission → `POST /me/workspaces/:name/up` → 202 → redirect vers `/workspaces` → la carte apparaît en `provisioning` avec polling actif.

Erreurs 422 : affichées inline sous le champ concerné (nom invalide, recipe inconnue, secret manquant).

---

## Polling & data flow

### Règles TanStack Query

**Modèle de données workspace** : deux appels sont nécessaires par workspace.
- `GET /me/workspaces` retourne les specs de config (`name`, `source`, `host`, `recipes`).
- `GET /me/workspaces/:name/status` retourne le statut live (`status`, `url`, `host_port`, `returncode`).
Le frontend combine les deux : la liste est chargée une fois, puis le statut est pollé individuellement pour les workspaces en état transitoire.

| Query | `staleTime` | `refetchInterval` |
|---|---|---|
| `GET /me` | 5 min | — |
| `GET /recipes` | 10 min | — |
| `GET /me/workspaces` (liste config) | 30 s | — |
| `GET /me/workspaces/:name/status` | 0 | 3 s si statut transitoire, sinon 10 s |
| `GET /admin/hosts` (admin only) | 2 min | — |

Statuts transitoires : `provisioning`, `stopping`, `deleting`.

Polling conditionnel : `refetchInterval: (query) => isTransient(query.state.data?.status) ? 3000 : 10_000`

### Mutations

- **up** : `onSuccess` invalide la liste ; workspace apparaît immédiatement en `provisioning`.
- **stop / delete** : `onMutate` applique le statut local `stopping`/`deleting` (UX optimiste) ; `onSettled` invalide la query.

### Client API

```typescript
// src/shared/api/client.ts
const BASE = import.meta.env.VITE_API_URL ?? ''

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'include', ...init })
  if (res.status === 401) {
    window.location.href = '/auth/login'
    throw new Error('unauthenticated')
  }
  return res
}
```

---

## Gestion d'erreurs

| Cas | Comportement |
|---|---|
| Erreur réseau / 5xx | Toast non-bloquant (shadcn/ui Sonner) |
| 401 | Intercepteur client → redirect `/auth/login` |
| 403 | `AdminGuard` affiche page "Accès refusé" |
| 422 | Erreur inline sur le champ du formulaire |
| 404 workspace | Redirect vers `/workspaces` |

---

## i18n

Détection dans l'ordre : `localStorage` → `navigator.language` → fallback `'en'`. Seuls `'en'` et `'fr'` sont implémentés ; toute autre langue du navigateur utilise `'en'`.

Toggle langue dans le menu profil : écrit dans `localStorage`, recharge les traductions sans rechargement de page.

Clés minimales à implémenter dans `en.json` et `fr.json` :

```json
{
  "workspaces": {
    "title": "Workspaces",
    "new": "New workspace",
    "status": {
      "running": "running", "stopped": "stopped",
      "provisioning": "provisioning", "failed": "failed", "unknown": "unknown"
    },
    "actions": { "open": "Open", "stop": "Stop", "start": "Start", "delete": "Delete", "retry": "Retry" }
  },
  "recipes": { "title": "Recipes" },
  "admin": { "hosts": "Hosts", "sharedRecipes": "Shared recipes" },
  "errors": { "forbidden": "Access denied", "notFound": "Not found" },
  "nav": { "profile": "Profile", "logout": "Log out", "theme": "Theme", "language": "Language" }
}
```

---

## Thème

Zustand `theme.ts` : initialisation depuis `localStorage ?? prefers-color-scheme`. Toggle bascule la classe `dark` sur `document.documentElement`. Tailwind `darkMode: 'class'`.

**Anti-flash** : script inline dans `index.html` avant le bundle React pour appliquer la classe `dark` immédiatement :

```html
<script>
  const t = localStorage.getItem('theme')
  const dark = t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
</script>
```

---

## Authentification

Flow OIDC entièrement géré côté backend (authlib). Le frontend :

1. **Login** : lien `<a href="/auth/login">` — le backend démarre le flow Keycloak.
2. **Callback** (`/auth/callback`) : `AuthCallback` appelle `GET /me`, hydrate Zustand (`user.ts`), redirige vers `/workspaces`.
3. **Session** : cookie HTTP-only géré par le backend. Pas de JWT côté frontend.
4. **`RequireAuth`** : `useSession()` retourne 401 → redirect `/auth/login`.
5. **`AdminGuard`** : lit `user.roles` depuis Zustand ; si `'admin'` absent → page 403.
6. **Logout** : lien vers `GET /auth/logout` (backend détruit la session et redirige).

---

## Tests

**Setup global** : `src/test/setup.ts` (RTL cleanup, msw server start/stop), wrapper `renderWithProviders()` (QueryClient fresh, Router, i18n EN, Zustand reset).

### Couverture minimale par feature

**auth/**
- `AuthCallback` hydrate le store Zustand après `GET /me` réussi
- `RequireAuth` redirige vers `/auth/login` si `GET /me` retourne 401

**workspaces/**
- `WorkspaceList` affiche les cartes avec les bons statuts
- `WorkspaceCard` : actions "Ouvrir" + "Stop" si running, "Démarrer" + "Supprimer" si stopped, actions désactivées si provisioning
- `WorkspaceCreate` : validation du nom (refus `../etc`), chips recipes togglables, soumission → 202 → redirect, erreur 422 inline
- `useWorkspaceOps` : polling actif si provisioning, arrêté si running

**recipes/**
- `RecipeCatalog` : liste chargée depuis msw
- `RecipePicker` : toggle chip sélectionne/désélectionne

**admin/**
- `AdminGuard` : bloque et affiche 403 si rôle admin absent
- `AdminHosts` : table affichée avec les hosts msw

**store/**
- `theme.ts` : toggle dark↔light, persistance localStorage
- `user.ts` : `setUser` hydrate, `clear` vide

**i18n/**
- Clés critiques rendues en EN et FR sur `WorkspaceList` et `WorkspaceCard`
