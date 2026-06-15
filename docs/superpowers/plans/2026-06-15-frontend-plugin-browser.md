# Frontend Plugin Browser — Plan d'implémentation

> **Pour les workers agentiques :** REQUIRED SUB-SKILL : Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans pour implémenter ce plan tâche par tâche. Les étapes utilisent la syntaxe checkbox (`- [ ]`) pour le suivi.

**Goal :** Navigateur de plugins Open VSX — barre de recherche debouncée, 4 tris, pagination infinie, fiche détail avec README markdown, sélection multiple — exposé comme composant contrôlé réutilisable, avec page hôte démo à `/profiles`.

**Architecture :** `PluginBrowser` reçoit `selectedIds: Set<string>` et `onToggle(id)` en props. Couche API dans `features/profiles/api/`, hooks TanStack Query dans `features/profiles/hooks/`, composants dans `features/profiles/components/`. Micro-patch backend pour rendre `q` optionnel (landing « populaires » quand vide).

**Tech Stack :** React 19 + TypeScript strict + TanStack Query v5 (`useInfiniteQuery`) + shadcn/ui + react-markdown + remark-gfm + @tailwindcss/typography + MSW v2 (tests)

---

## Fichiers

**Backend (modifiés) :**
- Modify: `backend/src/portal/routes/plugins.py`
- Modify: `backend/src/portal/openvsx.py`
- Modify: `backend/tests/test_openvsx.py`
- Modify: `backend/tests/routes/test_plugins.py`
- Modify: `LESSONS.md`

**Frontend (créés) :**
- Create: `frontend/src/features/profiles/api/types.ts`
- Create: `frontend/src/features/profiles/api/plugins.ts`
- Create: `frontend/src/features/profiles/hooks/useDebouncedValue.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginSearch.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginDetail.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginReadme.ts`
- Create: `frontend/src/features/profiles/components/PluginSearchBar.tsx`
- Create: `frontend/src/features/profiles/components/PluginSortSelect.tsx`
- Create: `frontend/src/features/profiles/components/PluginCard.tsx`
- Create: `frontend/src/features/profiles/components/PluginDetailDialog.tsx`
- Create: `frontend/src/features/profiles/components/PluginBrowser.tsx`
- Create: `frontend/src/features/profiles/PluginBrowserPage.tsx`
- Create: `frontend/src/features/profiles/__tests__/PluginBrowser.test.tsx`

**Frontend (modifiés) :**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/shared/layouts/AppShell.tsx`
- Modify: `frontend/src/test/handlers.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tailwind.config.ts`

---

### Task 1 : Backend — rendre `q` optionnel sur `GET /plugins/search`

**Files :**
- Modify: `backend/src/portal/openvsx.py`
- Modify: `backend/src/portal/routes/plugins.py`
- Modify: `backend/tests/test_openvsx.py`
- Modify: `backend/tests/routes/test_plugins.py`
- Modify: `LESSONS.md`

- [ ] **Step 1 : Écrire le test openvsx manquant (test rouge)**

Dans `backend/tests/test_openvsx.py`, ajouter après les tests de tri existants :

```python
async def test_search_without_query_omits_query_param():
    """search(None, sort='popular') → param 'query' absent de la requête HTTP."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    result = await client.search(None, sort="popular")

    assert isinstance(result, PluginSearchResult)
    assert len(captured) == 1
    assert "query" not in captured[0].url.params
    assert captured[0].url.params["sortBy"] == "downloadCount"
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/test_openvsx.py::test_search_without_query_omits_query_param -v
```

Attendu : FAILED (TypeError car `search` n'accepte pas `None`)

- [ ] **Step 3 : Modifier `openvsx.py` — `search()` accepte `query: str | None`**

Remplacer la méthode `search` dans `OpenVsxClient` :

```python
async def search(
    self, query: str | None = None, sort: str = "relevance", offset: int = 0, size: int = 24
) -> PluginSearchResult:
    sort_by = _SORT_MAP.get(sort, "relevance")
    key = f"search:{query or ''}:{sort_by}:{offset}:{size}"
    if cached := await self._search_cache.get(key):
        return cached
    params: dict[str, Any] = {
        "sortBy": sort_by,
        "sortOrder": "desc",
        "offset": offset,
        "size": size,
        "includeAllVersions": "false",
    }
    if query:
        params["query"] = query
    raw = await self._get("/api/-/search", params=params)
    result = PluginSearchResult(
        total=raw.get("totalSize", 0),
        offset=raw.get("offset", offset),
        items=[self._to_summary(e) for e in raw.get("extensions", [])],
    )
    await self._search_cache.set(key, result)
    return result
```

- [ ] **Step 4 : Modifier `plugins.py` — `q` optionnel**

```python
@router.get("/search", response_model=PluginSearchResult)
async def search_plugins(
    q: str | None = Query(default=None, min_length=1),
    sort: str = Query("relevance", pattern="^(relevance|popular|recent|rating)$"),
    offset: int = Query(0, ge=0),
    size: int = Query(24, ge=1, le=50),
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginSearchResult:
    try:
        return await client.search(q, sort=sort, offset=offset, size=size)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")
```

- [ ] **Step 5 : Ajouter un test de route pour search sans `q`**

Dans `backend/tests/routes/test_plugins.py`, ajouter dans la suite existante (chercher la fixture `client` et `mock_openvsx` pour s'aligner sur les patterns existants) :

```python
async def test_search_without_q_returns_results(
    client: AsyncClient, mock_openvsx: AsyncMock
) -> None:
    """GET /plugins/search sans q → appelle client.search(None, ...) → 200."""
    mock_openvsx.search.return_value = SEARCH_RESULT
    response = await client.get("/plugins/search")
    assert response.status_code == 200
    mock_openvsx.search.assert_called_once_with(None, sort="relevance", offset=0, size=24)
```

- [ ] **Step 6 : Lancer tous les tests backend**

```bash
cd backend && uv run pytest tests/test_openvsx.py tests/routes/test_plugins.py -v
```

Attendu : tous PASSED (y compris le nouveau test)

- [ ] **Step 7 : Consigner dans `LESSONS.md`**

Ajouter :
```
- [plugins] GET /api/plugins/search : q est désormais optionnel (min_length=1 si présent). Sans q, la clé `query` est absente de la requête Open VSX → l'API renvoie le top global trié par sortBy.
```

- [ ] **Step 8 : Commit**

```bash
git add backend/src/portal/openvsx.py backend/src/portal/routes/plugins.py backend/tests/test_openvsx.py backend/tests/routes/test_plugins.py LESSONS.md
git commit -m "feat(plugins): rendre le paramètre q optionnel sur /plugins/search"
```

---

### Task 2 : Dépendances frontend

**Files :** `frontend/package.json` (via npm)

- [ ] **Step 1 : Installer les paquets**

```bash
cd frontend && npm install react-markdown remark-gfm @tailwindcss/typography
```

- [ ] **Step 2 : Vérifier l'absence d'erreur de résolution**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -5
```

Attendu : 0 erreur (les nouveaux types sont inclus dans les paquets)

- [ ] **Step 3 : Commit**

```bash
cd frontend && git add package.json package-lock.json
git commit -m "chore(frontend): ajouter react-markdown remark-gfm @tailwindcss/typography"
```

---

### Task 3 : Configuration — proxy Vite + plugin Tailwind Typography

**Files :**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1 : Ajouter `/plugins` au proxy Vite**

Dans `frontend/vite.config.ts`, ajouter dans `server.proxy` (même pattern que les entrées existantes) :

```ts
'/plugins': { target: 'http://localhost:8080', changeOrigin: true },
```

Résultat attendu de la section `server.proxy` :

```ts
server: {
  proxy: {
    '/auth':    { target: 'http://localhost:8080', changeOrigin: true },
    '/me':      { target: 'http://localhost:8080', changeOrigin: true },
    '/admin':   { target: 'http://localhost:8080', changeOrigin: true },
    '/recipes': { target: 'http://localhost:8080', changeOrigin: true },
    '/plugins': { target: 'http://localhost:8080', changeOrigin: true },
    '/health':  { target: 'http://localhost:8080', changeOrigin: true },
  },
},
```

- [ ] **Step 2 : Ajouter le plugin Typography dans `tailwind.config.ts`**

Dans `frontend/tailwind.config.ts`, la section `plugins` contient déjà `require("tailwindcss-animate")`. Ajouter `require('@tailwindcss/typography')` :

```ts
plugins: [require("tailwindcss-animate"), require('@tailwindcss/typography')],
```

- [ ] **Step 3 : Vérifier le build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Attendu : 0 erreur

- [ ] **Step 4 : Commit**

```bash
cd frontend && git add vite.config.ts tailwind.config.ts
git commit -m "chore(frontend): proxy /plugins + plugin tailwindcss/typography"
```

---

### Task 4 : i18n — clés `profiles.plugins` (fr + en)

**Files :**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Lire les deux fichiers en entier**

```bash
cat frontend/src/i18n/fr.json
cat frontend/src/i18n/en.json
```

Repérer où finit le dernier objet de premier niveau (ex. `"errors": {...}`) pour savoir où insérer `"profiles"` et `"common"`.

- [ ] **Step 2 : Ajouter dans `fr.json`**

Ajouter avant l'accolade fermante de la racine :

```json
"profiles": {
  "plugins": {
    "title": "Plugins VSCode",
    "searchPlaceholder": "Rechercher une extension…",
    "empty": "Aucun plugin trouvé.",
    "loadMore": "Charger plus",
    "add": "Ajouter",
    "remove": "Retirer",
    "downloadsLabel": "téléch.",
    "selectedCount_one": "{{count}} plugin sélectionné",
    "selectedCount_other": "{{count}} plugins sélectionnés",
    "sort": {
      "relevance": "Pertinence",
      "popular": "Populaires",
      "recent": "Récents",
      "rating": "Mieux notés"
    },
    "errors": {
      "search": "Impossible de contacter le registre de plugins.",
      "detail": "Impossible de charger les détails du plugin.",
      "readme": "Impossible de charger le README."
    }
  }
},
"common": {
  "loading": "Chargement…"
}
```

Note : si une clé `"common"` existe déjà dans le fichier, fusionner `"loading"` dans l'objet existant plutôt que de dupliquer.

- [ ] **Step 3 : Ajouter dans `en.json`**

```json
"profiles": {
  "plugins": {
    "title": "VSCode Plugins",
    "searchPlaceholder": "Search extensions…",
    "empty": "No plugins found.",
    "loadMore": "Load more",
    "add": "Add",
    "remove": "Remove",
    "downloadsLabel": "dl",
    "selectedCount_one": "{{count}} plugin selected",
    "selectedCount_other": "{{count}} plugins selected",
    "sort": {
      "relevance": "Relevance",
      "popular": "Popular",
      "recent": "Recent",
      "rating": "Highest rated"
    },
    "errors": {
      "search": "Could not reach the plugin registry.",
      "detail": "Could not load plugin details.",
      "readme": "Could not load plugin README."
    }
  }
},
"common": {
  "loading": "Loading…"
}
```

- [ ] **Step 4 : Vérifier que les JSON sont valides**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/fr.json','utf8')); console.log('fr OK')"
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/en.json','utf8')); console.log('en OK')"
```

Attendu : `fr OK` et `en OK`

- [ ] **Step 5 : Commit**

```bash
cd frontend && git add src/i18n/fr.json src/i18n/en.json
git commit -m "feat(i18n): clés profiles.plugins fr+en"
```

---

### Task 5 : Couche API frontend

**Files :**
- Create: `frontend/src/features/profiles/api/types.ts`
- Create: `frontend/src/features/profiles/api/plugins.ts`

- [ ] **Step 1 : Créer `types.ts`**

```ts
export type PluginSort = 'relevance' | 'popular' | 'recent' | 'rating'

export interface PluginSummary {
  id: string
  namespace: string
  name: string
  display_name: string
  description: string
  version: string
  downloads: number
  rating: number | null
  icon_url: string | null
}

export interface PluginSearchResult {
  total: number
  offset: number
  items: PluginSummary[]
}

export interface PluginDetail extends PluginSummary {
  categories: string[]
  tags: string[]
  license: string | null
  readme_url: string | null
}
```

- [ ] **Step 2 : Créer `plugins.ts`**

`apiFetchJson` et `apiFetch` sont tous les deux exportés depuis `@/shared/api/client`.
`apiFetchJson<T>` retourne une `Promise<T>` en parsant le JSON (lève `ApiError` si !ok).
`apiFetch` retourne la `Response` brute (gère le redirect 401) — utile pour le readme texte.

```ts
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { PluginDetail, PluginSearchResult, PluginSort } from './types'

export const PLUGINS_PAGE_SIZE = 24

export function searchPlugins(params: {
  q: string
  sort: PluginSort
  offset: number
  size?: number
}): Promise<PluginSearchResult> {
  const qs = new URLSearchParams({
    sort: params.sort,
    offset: String(params.offset),
    size: String(params.size ?? PLUGINS_PAGE_SIZE),
  })
  if (params.q.trim()) qs.set('q', params.q.trim())
  return apiFetchJson<PluginSearchResult>(`/plugins/search?${qs}`)
}

export function getPlugin(namespace: string, name: string): Promise<PluginDetail> {
  return apiFetchJson<PluginDetail>(
    `/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
  )
}

export async function getPluginReadme(namespace: string, name: string): Promise<string> {
  const res = await apiFetch(
    `/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/readme`,
  )
  if (!res.ok) return ''
  return res.text()
}
```

- [ ] **Step 3 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "profiles"
```

Attendu : aucune erreur sur les fichiers `profiles/`.

- [ ] **Step 4 : Commit**

```bash
cd frontend && git add src/features/profiles/api/
git commit -m "feat(profiles): couche API plugins — types TS miroir des DTO backend"
```

---

### Task 6 : Hooks TanStack Query

**Files :**
- Create: `frontend/src/features/profiles/hooks/useDebouncedValue.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginSearch.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginDetail.ts`
- Create: `frontend/src/features/profiles/hooks/usePluginReadme.ts`

- [ ] **Step 1 : `useDebouncedValue.ts`**

```ts
import { useEffect, useState } from 'react'

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return debounced
}
```

- [ ] **Step 2 : `usePluginSearch.ts`**

```ts
import { useInfiniteQuery } from '@tanstack/react-query'
import { PLUGINS_PAGE_SIZE, searchPlugins } from '../api/plugins'
import type { PluginSort } from '../api/types'

export function usePluginSearch(query: string, sort: PluginSort) {
  return useInfiniteQuery({
    queryKey: ['plugins', 'search', query, sort],
    queryFn: ({ pageParam }) =>
      searchPlugins({ q: query, sort, offset: pageParam as number, size: PLUGINS_PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}
```

- [ ] **Step 3 : `usePluginDetail.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { getPlugin } from '../api/plugins'

export function usePluginDetail(namespace?: string, name?: string) {
  return useQuery({
    queryKey: ['plugins', 'detail', namespace, name],
    queryFn: () => getPlugin(namespace!, name!),
    enabled: Boolean(namespace && name),
  })
}
```

- [ ] **Step 4 : `usePluginReadme.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { getPluginReadme } from '../api/plugins'

export function usePluginReadme(namespace?: string, name?: string) {
  return useQuery({
    queryKey: ['plugins', 'readme', namespace, name],
    queryFn: () => getPluginReadme(namespace!, name!),
    enabled: Boolean(namespace && name),
    staleTime: 5 * 60 * 1000,
  })
}
```

- [ ] **Step 5 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "profiles"
```

Attendu : aucune erreur.

- [ ] **Step 6 : Commit**

```bash
cd frontend && git add src/features/profiles/hooks/
git commit -m "feat(profiles): hooks usePluginSearch usePluginDetail usePluginReadme useDebouncedValue"
```

---

### Task 7 : Composants atomiques — PluginSearchBar, PluginSortSelect, PluginCard

**Files :**
- Create: `frontend/src/features/profiles/components/PluginSearchBar.tsx`
- Create: `frontend/src/features/profiles/components/PluginSortSelect.tsx`
- Create: `frontend/src/features/profiles/components/PluginCard.tsx`

- [ ] **Step 1 : `PluginSearchBar.tsx`**

```tsx
import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'

interface Props {
  value: string
  onChange: (v: string) => void
}

export function PluginSearchBar({ value, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <div className="relative flex-1">
      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t('profiles.plugins.searchPlaceholder')}
        aria-label={t('profiles.plugins.searchPlaceholder')}
        className="pl-8"
      />
    </div>
  )
}
```

- [ ] **Step 2 : `PluginSortSelect.tsx`**

Vérifier que `@/components/ui/select` exporte bien `Select, SelectContent, SelectItem, SelectTrigger, SelectValue` (shadcn standard) avant d'écrire le fichier.

```tsx
import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { PluginSort } from '../api/types'

interface Props {
  value: PluginSort
  onChange: (v: PluginSort) => void
}

const SORTS: PluginSort[] = ['relevance', 'popular', 'recent', 'rating']

export function PluginSortSelect({ value, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <Select value={value} onValueChange={(v) => onChange(v as PluginSort)}>
      <SelectTrigger className="w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SORTS.map((s) => (
          <SelectItem key={s} value={s}>
            {t(`profiles.plugins.sort.${s}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
```

- [ ] **Step 3 : `PluginCard.tsx`**

```tsx
import { Puzzle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PluginSummary } from '../api/types'

const fmt = new Intl.NumberFormat(undefined, { notation: 'compact' })

interface Props {
  plugin: PluginSummary
  selected: boolean
  onToggle: () => void
  onOpen: () => void
}

export function PluginCard({ plugin, selected, onToggle, onOpen }: Props) {
  const { t } = useTranslation()
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen()
        }
      }}
      className={cn(
        'flex flex-col gap-2 rounded-lg border bg-card p-4 cursor-pointer transition-colors hover:bg-accent/50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected && 'ring-2 ring-primary',
      )}
    >
      <div className="flex items-start gap-3">
        {plugin.icon_url ? (
          <img
            src={plugin.icon_url}
            alt=""
            className="h-10 w-10 shrink-0 rounded object-contain"
            loading="lazy"
          />
        ) : (
          <Puzzle className="h-10 w-10 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{plugin.display_name}</div>
          <div className="truncate text-xs text-muted-foreground">{plugin.namespace}</div>
        </div>
        <Button
          size="sm"
          variant={selected ? 'secondary' : 'outline'}
          onClick={(e) => {
            e.stopPropagation()
            onToggle()
          }}
        >
          {t(selected ? 'profiles.plugins.remove' : 'profiles.plugins.add')}
        </Button>
      </div>
      <p className="line-clamp-2 text-sm text-muted-foreground">{plugin.description}</p>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>
          {fmt.format(plugin.downloads)} {t('profiles.plugins.downloadsLabel')}
        </span>
        {plugin.rating !== null && <span>★ {plugin.rating.toFixed(1)}</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 4 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "profiles"
```

Attendu : aucune erreur.

- [ ] **Step 5 : Commit**

```bash
cd frontend && git add src/features/profiles/components/PluginSearchBar.tsx src/features/profiles/components/PluginSortSelect.tsx src/features/profiles/components/PluginCard.tsx
git commit -m "feat(profiles): composants PluginSearchBar PluginSortSelect PluginCard"
```

---

### Task 8 : PluginDetailDialog

**Files :**
- Create: `frontend/src/features/profiles/components/PluginDetailDialog.tsx`

- [ ] **Step 1 : Créer `PluginDetailDialog.tsx`**

`react-markdown` est un module ESM. Dans Vite, l'import direct fonctionne.
`rehype-raw` n'est PAS activé — sécurité : le contenu Open VSX est tiers.

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { usePluginReadme } from '../hooks/usePluginReadme'
import type { PluginSummary } from '../api/types'

interface Props {
  plugin: PluginSummary | null
  selected: boolean
  onToggle: () => void
  onClose: () => void
}

export function PluginDetailDialog({ plugin, selected, onToggle, onClose }: Props) {
  const { t } = useTranslation()
  const { data: readme, isLoading } = usePluginReadme(plugin?.namespace, plugin?.name)

  return (
    <Dialog open={Boolean(plugin)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-y-auto">
        {plugin && (
          <>
            <DialogHeader>
              <DialogTitle>{plugin.display_name}</DialogTitle>
              <DialogDescription className="sr-only">
                {plugin.namespace} · v{plugin.version}
              </DialogDescription>
            </DialogHeader>
            <p className="text-sm text-muted-foreground">
              {plugin.namespace} · v{plugin.version}
            </p>
            <Button
              size="sm"
              variant={selected ? 'secondary' : 'default'}
              onClick={onToggle}
            >
              {t(selected ? 'profiles.plugins.remove' : 'profiles.plugins.add')}
            </Button>
            <div className="prose prose-sm prose-invert mt-4 max-w-none">
              {isLoading ? (
                <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{readme ?? ''}</ReactMarkdown>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "PluginDetailDialog\|react-markdown\|remark-gfm"
```

Attendu : aucune erreur.

- [ ] **Step 3 : Commit**

```bash
cd frontend && git add src/features/profiles/components/PluginDetailDialog.tsx
git commit -m "feat(profiles): PluginDetailDialog — README markdown via react-markdown+remark-gfm"
```

---

### Task 9 : PluginBrowser — orchestration

**Files :**
- Create: `frontend/src/features/profiles/components/PluginBrowser.tsx`

- [ ] **Step 1 : Créer `PluginBrowser.tsx`**

```tsx
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { usePluginSearch } from '../hooks/usePluginSearch'
import type { PluginSort, PluginSummary } from '../api/types'
import { PluginSearchBar } from './PluginSearchBar'
import { PluginSortSelect } from './PluginSortSelect'
import { PluginCard } from './PluginCard'
import { PluginDetailDialog } from './PluginDetailDialog'

interface Props {
  selectedIds: Set<string>
  onToggle: (id: string) => void
}

export function PluginBrowser({ selectedIds, onToggle }: Props) {
  const { t } = useTranslation()
  const [rawQuery, setRawQuery] = useState('')
  const [sort, setSort] = useState<PluginSort>('relevance')
  const [opened, setOpened] = useState<PluginSummary | null>(null)
  const query = useDebouncedValue(rawQuery, 300)

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    usePluginSearch(query, sort)

  const items = useMemo(() => data?.pages.flatMap((p) => p.items) ?? [], [data])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <PluginSearchBar value={rawQuery} onChange={setRawQuery} />
        <PluginSortSelect value={sort} onChange={setSort} />
      </div>

      {isError && (
        <p className="text-sm text-destructive">{t('profiles.plugins.errors.search')}</p>
      )}
      {isLoading && (
        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
      )}
      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('profiles.plugins.empty')}</p>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((p) => (
          <PluginCard
            key={p.id}
            plugin={p}
            selected={selectedIds.has(p.id)}
            onToggle={() => onToggle(p.id)}
            onOpen={() => setOpened(p)}
          />
        ))}
      </div>

      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {t('profiles.plugins.loadMore')}
          </Button>
        </div>
      )}

      <PluginDetailDialog
        plugin={opened}
        selected={opened ? selectedIds.has(opened.id) : false}
        onToggle={() => opened && onToggle(opened.id)}
        onClose={() => setOpened(null)}
      />
    </div>
  )
}
```

- [ ] **Step 2 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "profiles"
```

- [ ] **Step 3 : Commit**

```bash
cd frontend && git add src/features/profiles/components/PluginBrowser.tsx
git commit -m "feat(profiles): PluginBrowser — orchestration recherche/tri/pagination/sélection"
```

---

### Task 10 : PluginBrowserPage + routing + navigation AppShell

**Files :**
- Create: `frontend/src/features/profiles/PluginBrowserPage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/shared/layouts/AppShell.tsx`

- [ ] **Step 1 : Créer `PluginBrowserPage.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PluginBrowser } from './components/PluginBrowser'

export default function PluginBrowserPage() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">{t('profiles.plugins.title')}</h1>
      {selected.size > 0 && (
        <p className="text-sm text-muted-foreground">
          {t('profiles.plugins.selectedCount', { count: selected.size })} :{' '}
          {[...selected].join(', ')}
        </p>
      )}
      <PluginBrowser selectedIds={selected} onToggle={toggle} />
    </div>
  )
}
```

- [ ] **Step 2 : Modifier `router.tsx`**

Ajouter l'import lazy (après `RecipeCatalog`) :

```ts
const PluginBrowserPage = lazy(() => import('@/features/profiles/PluginBrowserPage'))
```

Ajouter la route dans `children` (après `/recipes`) :

```tsx
{ path: '/profiles', element: <Wrap><PluginBrowserPage /></Wrap> },
```

- [ ] **Step 3 : Modifier `AppShell.tsx`**

Ajouter `SquareLibrary` aux imports lucide existants :

```ts
import { LayoutDashboard, Puzzle, LogOut, Sun, Moon, Globe, SquareLibrary } from 'lucide-react'
```

Ajouter le lien rail après le lien `/recipes` (et avant le `div className="mt-auto"`) :

```tsx
<NavLink
  to="/profiles"
  className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
  title={t('profiles.plugins.title')}
>
  <SquareLibrary size={18} />
</NavLink>
```

- [ ] **Step 4 : Vérifier TypeScript + import**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Attendu : 0 erreur.

- [ ] **Step 5 : Commit**

```bash
cd frontend && git add src/features/profiles/PluginBrowserPage.tsx src/router.tsx src/shared/layouts/AppShell.tsx
git commit -m "feat(profiles): route /profiles + navigation AppShell (icône SquareLibrary)"
```

---

### Task 11 : MSW handlers + tests PluginBrowser

**Files :**
- Modify: `frontend/src/test/handlers.ts`
- Create: `frontend/src/features/profiles/__tests__/PluginBrowser.test.tsx`

- [ ] **Step 1 : Lire `handlers.ts` et `renderWithProviders.tsx`**

```bash
cat frontend/src/test/handlers.ts
cat frontend/src/test/renderWithProviders.tsx
```

Vérifier l'import de `renderWithProviders` utilisé dans les tests existants pour reproduire le même pattern.

- [ ] **Step 2 : Ajouter les handlers MSW par défaut pour plugins**

Dans `frontend/src/test/handlers.ts`, ajouter à la fin du tableau `handlers` :

```ts
// Handlers plugins (défauts — overridables par test via server.use)
http.get('/plugins/search', () =>
  HttpResponse.json({
    total: 1,
    offset: 0,
    items: [{
      id: 'ms-python.python',
      namespace: 'ms-python',
      name: 'python',
      display_name: 'Python',
      description: 'Python language support',
      version: '2024.0.1',
      downloads: 100000,
      rating: 4.5,
      icon_url: null,
    }],
  })
),
http.get('/plugins/:namespace/:name/readme', () =>
  new HttpResponse('', { headers: { 'Content-Type': 'text/markdown' } })
),
http.get('/plugins/:namespace/:name', () =>
  HttpResponse.json({
    id: 'ms-python.python',
    namespace: 'ms-python',
    name: 'python',
    display_name: 'Python',
    description: 'Python language support',
    version: '2024.0.1',
    downloads: 100000,
    rating: 4.5,
    icon_url: null,
    categories: ['Programming Languages'],
    tags: ['python'],
    license: null,
    readme_url: null,
  })
),
```

- [ ] **Step 3 : Écrire le test**

Créer `frontend/src/features/profiles/__tests__/PluginBrowser.test.tsx` :

```tsx
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { PluginBrowser } from '../components/PluginBrowser'

const MOCK_PLUGIN = {
  id: 'ms-python.python',
  namespace: 'ms-python',
  name: 'python',
  display_name: 'Python',
  description: 'Python language support',
  version: '2024.0.1',
  downloads: 100000,
  rating: 4.5,
  icon_url: null,
}

function renderBrowser(
  selectedIds: Set<string> = new Set(),
  onToggle: (id: string) => void = () => {},
) {
  return renderWithProviders(
    <PluginBrowser selectedIds={selectedIds} onToggle={onToggle} />,
  )
}

describe('PluginBrowser', () => {
  it('affiche les plugins au rendu initial (query vide, sort=relevance)', async () => {
    renderBrowser()
    await waitFor(() => expect(screen.getByText('Python')).toBeInTheDocument())
    expect(screen.getByText('Python language support')).toBeInTheDocument()
  })

  it('change de tri → refetch avec le nouveau sort', async () => {
    const user = userEvent.setup()
    let capturedSort: string | null = null

    server.use(
      http.get('/plugins/search', ({ request }) => {
        capturedSort = new URL(request.url).searchParams.get('sort')
        return HttpResponse.json({ total: 1, offset: 0, items: [MOCK_PLUGIN] })
      }),
    )

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))

    // Ouvrir le Select et choisir "Populaires"
    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByRole('option', { name: /populaire/i }))

    await waitFor(() => expect(capturedSort).toBe('popular'))
  })

  it('clic sur Ajouter → appelle onToggle avec l\'id du plugin', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    renderBrowser(new Set(), onToggle)
    await waitFor(() => screen.getByText('Python'))

    await user.click(screen.getByRole('button', { name: /ajouter/i }))
    expect(onToggle).toHaveBeenCalledWith('ms-python.python')
  })

  it('carte sélectionnée → classe ring-primary visible, bouton dit "Retirer"', async () => {
    renderBrowser(new Set(['ms-python.python']))
    await waitFor(() => screen.getByText('Python'))

    expect(screen.getByRole('button', { name: /retirer/i })).toBeInTheDocument()
    // La div carte possède ring-primary
    const removeBtn = screen.getByRole('button', { name: /retirer/i })
    const card = removeBtn.closest('[role="button"]')
    expect(card?.className).toContain('ring-primary')
  })

  it('clic sur le corps de la carte → dialog détail visible', async () => {
    const user = userEvent.setup()

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))

    // Cliquer sur la description (corps de la carte, pas le bouton toggle)
    await user.click(screen.getByText('Python language support'))

    await waitFor(() => {
      const dialog = screen.getByRole('dialog')
      expect(dialog).toBeInTheDocument()
      expect(within(dialog).getByText('Python')).toBeInTheDocument()
    })
  })

  it('dialog affiche le README markdown rendu', async () => {
    const user = userEvent.setup()

    server.use(
      http.get('/plugins/:namespace/:name/readme', () =>
        new HttpResponse('# Python README', { headers: { 'Content-Type': 'text/markdown' } }),
      ),
    )

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))
    await user.click(screen.getByText('Python language support'))

    await waitFor(() => screen.getByRole('dialog'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Python README')
    })
  })

  it('affiche le bouton "Charger plus" quand total > items chargés', async () => {
    server.use(
      http.get('/plugins/search', () =>
        HttpResponse.json({ total: 50, offset: 0, items: [MOCK_PLUGIN] }),
      ),
    )
    renderBrowser()
    await waitFor(() => screen.getByRole('button', { name: /charger plus/i }))
  })

  it('pas de bouton "Charger plus" quand tout est chargé', async () => {
    renderBrowser() // handler par défaut : total=1, 1 item
    await waitFor(() => screen.getByText('Python'))
    expect(screen.queryByRole('button', { name: /charger plus/i })).not.toBeInTheDocument()
  })

  it('erreur 502 → affiche le message d\'erreur traduit', async () => {
    server.use(
      http.get('/plugins/search', () =>
        HttpResponse.json({ detail: 'Bad Gateway' }, { status: 502 }),
      ),
    )
    renderBrowser()
    await waitFor(() =>
      expect(screen.getByText(/impossible de contacter/i)).toBeInTheDocument(),
    )
  })
})
```

- [ ] **Step 4 : Lancer les tests du plugin browser**

```bash
cd frontend && npx vitest run src/features/profiles/__tests__/PluginBrowser.test.tsx --reporter=verbose
```

Attendu : 8 tests PASSED.

Si le test "change de tri" échoue à cause du Radix Select en jsdom (le popover ne s'ouvre pas), adapter en utilisant `fireEvent.change` sur l'élément hidden sous-jacent :

```tsx
// Alternative si Radix Select ne répond pas en jsdom :
const select = document.querySelector('select[name]') // ou chercher l'input hidden
fireEvent.change(select!, { target: { value: 'popular' } })
```

- [ ] **Step 5 : Lancer la suite complète**

```bash
cd frontend && npx vitest run --reporter=verbose 2>&1 | tail -15
```

Attendu : tous les tests passent, 0 régression.

- [ ] **Step 6 : Commit**

```bash
cd frontend && git add src/test/handlers.ts src/features/profiles/__tests__/
git commit -m "test(profiles): PluginBrowser — 8 cas MSW (rendu, tri, sélection, dialog, README, pagination, erreur)"
```

---

### Vérification finale (Definition of Done)

- [ ] `cd backend && uv run pytest -v 2>&1 | tail -5` → tous PASSED
- [ ] `cd frontend && npx vitest run 2>&1 | tail -5` → tous PASSED, 0 régression
- [ ] `cd frontend && npx tsc --noEmit` → 0 erreur TypeScript
- [ ] Aucun fichier > 300 lignes :
  ```bash
  wc -l frontend/src/features/profiles/**/*.tsx frontend/src/features/profiles/api/*.ts frontend/src/features/profiles/hooks/*.ts 2>/dev/null | sort -rn | head -10
  ```
- [ ] Aucune chaîne en dur dans les composants (hors tests) : `grep -r '"[A-Z]' frontend/src/features/profiles/components/ --include="*.tsx"`
- [ ] Route `/profiles` accessible dans le navigateur (vérif manuelle) : landing « populaires » affichée sans saisie
- [ ] Icône SquareLibrary visible dans le rail de navigation
