# MCP Runtime — Plan 7 : UI de curation par grant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre, dans l'UI de gestion des apikeys MCP, d'éditer la **curation par grant** : le mode d'exposition (`all` / `allowlist` / `denylist`) et la liste `expose` de noms d'outils, en plus du choix de clé déjà existant.

**Architecture:** Changement **frontend-only** — le backend supporte déjà `expose_mode`/`expose` (modèle `GrantSet`, `set_grant`/`list_grants`, colonnes DB ; appliqués par l'agrégation runtime). On étend les types TS (`MCPGrant`, `GrantSetBody`), on ajoute un composant réutilisable d'édition de liste de chaînes (`ExposeEditor`), et on enrichit `GrantRow`/`GrantEditor` (`features/mcp/MCPApikeys.tsx`) pour piloter `expose_mode` + `expose`. Mutation immédiate conservée (PUT à chaque changement, comme le choix de clé actuel). i18n en+fr. Tests Vitest + MSW.

**Hors périmètre :** affichage de la santé (Plan 6 `get_health`) dans le registre + polling `refetchInterval` — nécessite d'enrichir la route `GET /me/mcp/backends` avec le statut santé (sous-lot « 7-bis » séparé, backend + frontend). Ce plan ne traite que la curation.

**Tech Stack:** React 19, Vite 8, TypeScript 6 strict, TanStack Query 5, react-i18next 17, shadcn/ui (Select, Input, Button, Badge), Vitest 4 + React Testing Library + MSW 2. Tests : `renderWithProviders` (`src/test/renderWithProviders.tsx`), MSW (`src/test/server.ts` + `handlers.ts`).

## Global Constraints

- TypeScript strict ; aucun `any`.
- Server state via TanStack Query (hooks existants `useGrants`/`useSetGrant`) ; pas de nouvel état serveur custom.
- Composants : shadcn/ui (`@/components/ui/*`) ; pas de react-hook-form/zod (le projet n'en utilise pas — état local `useState`).
- i18n : toute chaîne visible passe par `t('mcp.apikeys.…')` ; clés ajoutées en `en.json` ET `fr.json` (parité stricte).
- Tests : `describe`/`it` (PAS `test`) ; `renderWithProviders` ; MSW pour l'API ; `userEvent.setup()`. Lint frontend propre (`tsc -b`). Sortie de test sans warning.
- Mutation immédiate (le grant est ré-écrit à chaque modification de clé/mode/liste), cohérent avec le `GrantRow` existant.
- Commandes : `cd /d/srcs/devpod-ui/frontend && npm run test` (vitest run), `npm run build` (tsc -b + vite build) pour le typecheck.
- Branche `dev` ; commits FR conventionnels ; TDD (test rouge → impl → vert → commit).

---

## Surface existante consommée

- `frontend/src/features/mcp/api.ts` :
  - `interface MCPGrant { apikey_id; backend_id; backend_key_id }` — à étendre.
  - `interface GrantSetBody { backend_id; backend_key_id: string | null }` — à étendre.
  - `useGrants(apikeyId)`, `useSetGrant(apikeyId)` (PUT `/me/mcp/apikeys/{id}/grants`), `useBackends`, `useBackendKeys`.
- `frontend/src/features/mcp/MCPApikeys.tsx` :
  - `GrantEditor({ apikeyId })` (l.125) — map les backends → `GrantRow` ; `onSet` appelle `setGrant.mutate({ backend_id, backend_key_id })`.
  - `GrantRow({ backendId, backendName, namespace, granted, currentKeyId, onSet, onRemove })` (l.177) — `Select` de clé ; `PUBLIC_GRANT = '__public__'` sentinelle.
- Backend (déjà livré) : `GrantSet(backend_id, backend_key_id, expose_mode: Literal["all","allowlist","denylist"]="all", expose: list[str]=[])` ; `set_grant`/`list_grants` portent ces colonnes ; le PUT `/me/mcp/apikeys/{id}/grants` accepte et persiste `expose_mode`+`expose`.
- i18n existant `mcp.apikeys.*` (en.json/fr.json) : `grantsTitle, grantsHint, selectKey, publicAccess, …`.
- MSW `src/test/handlers.ts` l.211-212 : `GET …/grants` → `[]` ; `PUT …/grants` → `{apikey_id, backend_id}`.
- shadcn : `@/components/ui/{select,input,button,badge,label}`.

---

### Task 1 : Types + `ExposeEditor` (composant liste de chaînes) + i18n

**Files:**
- Modify: `frontend/src/features/mcp/api.ts`
- Create: `frontend/src/features/mcp/ExposeEditor.tsx`
- Create: `frontend/src/features/mcp/ExposeEditor.test.tsx`
- Modify: `frontend/src/i18n/en.json`, `frontend/src/i18n/fr.json`

**Interfaces:**
- Produces:
  - `MCPGrant` et `GrantSetBody` gagnent `expose_mode: 'all' | 'allowlist' | 'denylist'` et `expose: string[]`.
  - `ExposeMode` type alias exporté : `export type ExposeMode = 'all' | 'allowlist' | 'denylist'`.
  - Composant `ExposeEditor({ value: string[]; onChange: (next: string[]) => void; disabled?: boolean })` : input + bouton « ajouter » (et Enter) pour ajouter un nom, chaque entrée affichée avec un bouton de retrait. Dédoublonne et ignore les chaînes vides.

- [ ] **Step 1: Étendre les types (`api.ts`)**

Dans `frontend/src/features/mcp/api.ts` :

```typescript
export type ExposeMode = 'all' | 'allowlist' | 'denylist'

export interface MCPGrant {
  apikey_id: string
  backend_id: string
  backend_key_id: string
  expose_mode: ExposeMode
  expose: string[]
}

export interface GrantSetBody {
  backend_id: string
  // null = backend public (sans authentification) : aucune clé de service
  backend_key_id: string | null
  expose_mode: ExposeMode
  expose: string[]
}
```

- [ ] **Step 2: Écrire le test rouge de `ExposeEditor`**

Créer `frontend/src/features/mcp/ExposeEditor.test.tsx` :

```tsx
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ExposeEditor } from './ExposeEditor'

describe('ExposeEditor', () => {
  it('ajoute un nom via le bouton et le remonte', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={[]} onChange={onChange} />)

    await user.type(screen.getByRole('textbox'), 'search')
    await user.click(screen.getByRole('button', { name: /add|ajouter/i }))

    expect(onChange).toHaveBeenCalledWith(['search'])
  })

  it('affiche les valeurs et permet de retirer', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={['a', 'b']} onChange={onChange} />)

    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    // retirer 'a' (le 1er bouton de retrait)
    await user.click(screen.getAllByRole('button', { name: /remove|retirer/i })[0])
    expect(onChange).toHaveBeenCalledWith(['b'])
  })

  it('ignore les doublons et les chaînes vides', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={['a']} onChange={onChange} />)

    await user.type(screen.getByRole('textbox'), 'a')
    await user.click(screen.getByRole('button', { name: /add|ajouter/i }))
    expect(onChange).not.toHaveBeenCalled()  // 'a' déjà présent
  })
})
```

- [ ] **Step 3: Lancer (rouge)**

Run: `cd /d/srcs/devpod-ui/frontend && npm run test -- ExposeEditor`
Expected : échec (module `./ExposeEditor` introuvable).

- [ ] **Step 4: Implémenter `ExposeEditor`**

Créer `frontend/src/features/mcp/ExposeEditor.tsx` :

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function ExposeEditor({
  value,
  onChange,
  disabled,
}: {
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState('')

  const add = () => {
    const name = draft.trim()
    if (!name || value.includes(name)) return
    onChange([...value, name])
    setDraft('')
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-1.5">
        <Input
          value={draft}
          disabled={disabled}
          placeholder={t('mcp.apikeys.exposePlaceholder')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          className="h-8"
        />
        <Button type="button" size="sm" variant="secondary" disabled={disabled} onClick={add}>
          {t('mcp.apikeys.exposeAdd')}
        </Button>
      </div>
      {value.length === 0 ? (
        <span className="text-xs text-muted-foreground">{t('mcp.apikeys.exposeEmpty')}</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {value.map((name) => (
            <Badge key={name} variant="secondary" className="gap-1 font-mono text-xs">
              {name}
              <button
                type="button"
                aria-label={t('mcp.apikeys.exposeRemove')}
                disabled={disabled}
                onClick={() => onChange(value.filter((n) => n !== name))}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Ajouter les clés i18n**

Dans `frontend/src/i18n/en.json`, section `mcp.apikeys`, ajouter :

```json
"exposeModeLabel": "Tool curation",
"exposeModeAll": "All tools",
"exposeModeAllowlist": "Only listed",
"exposeModeDenylist": "All except listed",
"exposePlaceholder": "Tool name…",
"exposeAdd": "Add",
"exposeRemove": "Remove",
"exposeEmpty": "No tool listed."
```

Dans `frontend/src/i18n/fr.json`, section `mcp.apikeys`, ajouter (parité) :

```json
"exposeModeLabel": "Curation des outils",
"exposeModeAll": "Tous les outils",
"exposeModeAllowlist": "Seulement listés",
"exposeModeDenylist": "Tous sauf listés",
"exposePlaceholder": "Nom d'outil…",
"exposeAdd": "Ajouter",
"exposeRemove": "Retirer",
"exposeEmpty": "Aucun outil listé."
```

- [ ] **Step 6: Lancer (vert) + typecheck**

Run: `cd /d/srcs/devpod-ui/frontend && npm run test -- ExposeEditor` → 3 tests PASSED.
Run: `cd /d/srcs/devpod-ui/frontend && npm run build` → `tsc -b` sans erreur (types `api.ts` cohérents). (Si `vite build` est trop long/inutile ici, au minimum `npx tsc -b` doit passer.)

- [ ] **Step 7: Commit**

```bash
cd /d/srcs/devpod-ui && git add frontend/src/features/mcp/api.ts frontend/src/features/mcp/ExposeEditor.tsx frontend/src/features/mcp/ExposeEditor.test.tsx frontend/src/i18n/en.json frontend/src/i18n/fr.json
git commit -m "feat(mcp-ui): types curation (expose_mode/expose) + ExposeEditor + i18n"
```

---

### Task 2 : `GrantRow` — sélecteur de mode + liste, câblé à `useSetGrant`

**Files:**
- Modify: `frontend/src/features/mcp/MCPApikeys.tsx`
- Modify: `frontend/src/features/mcp/MCPApikeys.test.tsx`
- Modify: `frontend/src/test/handlers.ts` (le PUT renvoie les champs envoyés)

**Interfaces:**
- Consumes: `ExposeMode`, `ExposeEditor`, `useSetGrant` (étendu).
- Produces: `GrantRow` édite `expose_mode` (Select) et, si mode ≠ `all`, la liste `expose` (`ExposeEditor`) ; chaque changement déclenche `onSet({ backend_key_id, expose_mode, expose })`. `GrantEditor` passe `currentExposeMode`/`currentExpose` depuis le grant et relaie au `setGrant.mutate`.

- [ ] **Step 1: Écrire le test rouge (intégration)**

Dans `frontend/src/features/mcp/MCPApikeys.test.tsx`, ajouter un test qui : monte la page avec un backend + une apikey, configure un grant en mode `allowlist` avec un outil, et vérifie que le PUT `/grants` reçoit `expose_mode: 'allowlist'` et `expose: ['search']`. Capturer le body via un handler MSW dédié :

```tsx
it('enregistre la curation allowlist avec un outil', async () => {
  const { server } = await import('@/test/server')
  const { http, HttpResponse } = await import('msw')
  let putBody: unknown = null
  server.use(
    http.get('/me/mcp/backends', () =>
      HttpResponse.json([
        { id: 'b1', owner_login: 'alice', namespace: 'rag', name: 'RAG',
          url: 'https://rag/mcp', transport: 'streamable_http', enabled: true,
          created_at: '', updated_at: '' },
      ]),
    ),
    http.get('/me/mcp/apikeys', () =>
      HttpResponse.json([
        { id: 'ak1', owner_login: 'alice', label: 'Laptop', revoked: false, created_at: '' },
      ]),
    ),
    http.get('/me/mcp/apikeys/:id/grants', () =>
      HttpResponse.json([
        { apikey_id: 'ak1', backend_id: 'b1', backend_key_id: null,
          expose_mode: 'all', expose: [] },
      ]),
    ),
    http.put('/me/mcp/apikeys/:id/grants', async ({ request }) => {
      putBody = await request.json()
      return HttpResponse.json({ apikey_id: 'ak1', backend_id: 'b1' })
    }),
  )

  const user = userEvent.setup()
  renderWithProviders(<MCPApikeys />)

  // ouvrir/atteindre l'éditeur de grant du backend rag, choisir le mode allowlist
  // (le Select de mode porte un aria-label/texte via t('mcp.apikeys.exposeModeLabel'))
  const modeSelect = await screen.findByLabelText(/tool curation|curation des outils/i)
  await user.click(modeSelect)
  await user.click(await screen.findByText(/only listed|seulement listés/i))

  // ajouter l'outil 'search'
  await user.type(screen.getByPlaceholderText(/tool name|nom d'outil/i), 'search')
  await user.click(screen.getByRole('button', { name: /^add$|^ajouter$/i }))

  await waitFor(() => {
    expect(putBody).toMatchObject({
      backend_id: 'b1',
      expose_mode: 'allowlist',
      expose: ['search'],
    })
  })
})
```

> Note implémenteur : adapter les sélecteurs (`findByLabelText`, textes des options) à l'implémentation réelle du `Select` shadcn (qui peut nécessiter `getByRole('combobox')` + ouverture). Le but du test : prouver que le body du PUT contient `expose_mode` + `expose`. Reuse les imports existants du fichier (`renderWithProviders`, `userEvent`, `screen`, `waitFor`, `MCPApikeys`).

- [ ] **Step 2: Lancer (rouge)**

Run: `cd /d/srcs/devpod-ui/frontend && npm run test -- MCPApikeys`
Expected : le nouveau test échoue (pas de sélecteur de mode / le PUT n'envoie pas expose_mode).

- [ ] **Step 3: Implémenter `GrantRow` + câblage `GrantEditor`**

Dans `frontend/src/features/mcp/MCPApikeys.tsx` :

1. Importer `ExposeEditor` et `ExposeMode` :
```tsx
import { ExposeEditor } from './ExposeEditor'
import type { ExposeMode } from './api'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```
(le `Select` est déjà importé — vérifier.)

2. `GrantEditor` : passer le mode/liste courants et les relayer dans `onSet` :
```tsx
{backends.map((b) => {
  const current = grants.find((g) => g.backend_id === b.id)
  return (
    <GrantRow
      key={b.id}
      backendId={b.id}
      backendName={b.name}
      namespace={b.namespace}
      granted={current !== undefined}
      currentKeyId={current?.backend_key_id ?? null}
      currentExposeMode={current?.expose_mode ?? 'all'}
      currentExpose={current?.expose ?? []}
      onSet={(body) =>
        setGrant.mutate(
          { backend_id: b.id, ...body },
          { onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')) },
        )
      }
      onRemove={() =>
        delGrant.mutate(b.id, {
          onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
        })
      }
    />
  )
})}
```

3. `GrantRow` : nouvelle signature + UI mode/liste. La ligne « clé » reste ; en-dessous, le sélecteur de mode et (conditionnel) l'éditeur de liste. Chaque changement émet l'état complet courant :

```tsx
function GrantRow({
  backendId, backendName, namespace, granted, currentKeyId,
  currentExposeMode, currentExpose, onSet, onRemove,
}: {
  backendId: string
  backendName: string
  namespace: string
  granted: boolean
  currentKeyId: string | null
  currentExposeMode: ExposeMode
  currentExpose: string[]
  onSet: (body: { backend_key_id: string | null; expose_mode: ExposeMode; expose: string[] }) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const { data: keys = [] } = useBackendKeys(backendId)

  const keyValue = !granted ? '' : (currentKeyId ?? PUBLIC_GRANT)

  const emit = (over: Partial<{ backend_key_id: string | null; expose_mode: ExposeMode; expose: string[] }>) =>
    onSet({
      backend_key_id: currentKeyId,
      expose_mode: currentExposeMode,
      expose: currentExpose,
      ...over,
    })

  return (
    <div className="flex flex-col gap-2 border-b pb-2 last:border-0">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">{backendName}</span>
        <Badge variant="outline" className="font-mono text-xs">{namespace}</Badge>
        <Select
          value={keyValue}
          onValueChange={(v) => emit({ backend_key_id: v === PUBLIC_GRANT ? null : v })}
        >
          <SelectTrigger className="ml-auto h-8 w-44">
            <SelectValue placeholder={t('mcp.apikeys.selectKey')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={PUBLIC_GRANT}>{t('mcp.apikeys.publicAccess')}</SelectItem>
            {keys.map((k) => (
              <SelectItem key={k.id} value={k.id}>{k.slug}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {granted && (
          <Button size="sm" variant="ghost" className="text-destructive" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      {granted && (
        <div className="flex flex-col gap-1.5 pl-1">
          <Select
            value={currentExposeMode}
            onValueChange={(v) => emit({ expose_mode: v as ExposeMode })}
          >
            <SelectTrigger aria-label={t('mcp.apikeys.exposeModeLabel')} className="h-8 w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('mcp.apikeys.exposeModeAll')}</SelectItem>
              <SelectItem value="allowlist">{t('mcp.apikeys.exposeModeAllowlist')}</SelectItem>
              <SelectItem value="denylist">{t('mcp.apikeys.exposeModeDenylist')}</SelectItem>
            </SelectContent>
          </Select>
          {currentExposeMode !== 'all' && (
            <ExposeEditor value={currentExpose} onChange={(next) => emit({ expose: next })} />
          )}
        </div>
      )}
    </div>
  )
}
```

> Note implémenteur : `emit` part de l'état COURANT (props `current*`) + l'override. Comme la mutation invalide `QK.grants` (onSuccess) et que les props proviennent de `useGrants`, l'état se reflète au refetch. Pour le mode `all`, `expose` est envoyé tel quel (le backend l'ignore). Vérifier que `Select` shadcn rend bien un élément accessible via `aria-label` (sinon, ajouter un `<Label>` associé et ajuster le test à `getByRole('combobox')`).

- [ ] **Step 4: Mettre à jour le handler MSW par défaut**

Dans `frontend/src/test/handlers.ts`, le `GET …/grants` par défaut renvoie `[]` (inchangé). S'assurer que le PUT par défaut (l.212) reste valide. Aucun changement requis si les tests qui ont besoin du body utilisent `server.use(...)` localement (cf. Task 2 Step 1).

- [ ] **Step 5: Lancer (vert) + typecheck**

Run: `cd /d/srcs/devpod-ui/frontend && npm run test -- MCPApikeys` → tous les tests (existants + nouveau) PASSED.
Run: `cd /d/srcs/devpod-ui/frontend && npm run test` → suite frontend complète verte, 0 warning.
Run: `cd /d/srcs/devpod-ui/frontend && npm run build` → `tsc -b` sans erreur.

- [ ] **Step 6: Commit**

```bash
cd /d/srcs/devpod-ui && git add frontend/src/features/mcp/MCPApikeys.tsx frontend/src/features/mcp/MCPApikeys.test.tsx frontend/src/test/handlers.ts
git commit -m "feat(mcp-ui): curation par grant (mode all/allowlist/denylist + liste expose)"
```

---

## Validation finale du plan

- [ ] `cd /d/srcs/devpod-ui/frontend && npm run test` → toute la suite frontend verte, 0 warning.
- [ ] `cd /d/srcs/devpod-ui/frontend && npm run build` → `tsc -b` + build sans erreur.
- [ ] Parité i18n en/fr vérifiée (mêmes clés `mcp.apikeys.expose*`).
- [ ] Push → CI (job frontend `tsc + vitest`) vert.
- [ ] Mettre à jour `.superpowers/sdd/progress-runtime.md` (journal Plan 7).

## Couverture spec (auto-review)

- Spec §12 / §8.2-8.3 curation par grant éditable côté UI (`expose_mode` + `expose`) : Tasks 1-2. Le backend applique déjà la curation à l'agrégation (Plan 3 `_curation_allows`).
- Mutation immédiate cohérente avec l'UX existante du choix de clé.
- **Hors de ce lot (noté)** : affichage santé/polling (enrichir `GET /me/mcp/backends` avec `get_health` + `refetchInterval`) = sous-lot 7-bis ; push serveur→client = hors d'atteinte SDK 1.28 (LESSONS).
