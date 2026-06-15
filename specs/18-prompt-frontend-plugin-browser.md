# Chantier — Frontend : navigateur de plugins Open VSX (recherche, tri, fiche)

> Dépôt **devpod-ui**, dossier `frontend/`. Ce chantier construit l'UX qui consomme le proxy
> Open VSX déjà livré (`/api/plugins/*`). C'est la brique « sélection de plugins » de la future
> page **Profil VSCode**. Le CRUD des profils (persistance YAML) est un chantier **séparé** : ici
> on s'arrête à un composant `PluginBrowser` réutilisable + une page hôte de démonstration.

## 0. Préalables (avant toute écriture)

1. Lis `CLAUDE.md`, `LESSONS.md`, et **mime les patterns frontend existants** :
   - routing : `frontend/src/router.tsx` (routes lazy par *feature*, `<Wrap><Suspense>`).
   - data : `@tanstack/react-query` (QueryClient configuré dans `main.tsx`).
   - UI : composants **shadcn/ui** sous `@/components/ui/*` (Dialog, Select, Input, Button,
     Separator, etc.), helper `cn` (`@/lib/utils`), icônes `lucide-react`, toasts `sonner`.
   - i18n : **toute chaîne visible passe par i18next** ; ajoute les clés selon la structure
     existante (`@/i18n` / fichiers de locales `fr`/`en`). Aucune chaîne en dur.
   - état : `zustand` si besoin d'état partagé ; sinon état local.
   - structure : nouvelle *feature* sous `@/features/profiles/`.
2. Branche `dev` uniquement. Commits conventionnels **en français**. Aucun fichier > 300 lignes.
3. TypeScript strict : pas de `any` non justifié, types explicites sur les frontières API.
4. Inspecte une *feature* existante (ex. `@/features/recipes/RecipeCatalog`) pour réutiliser le
   style des cartes, des états de chargement/vide/erreur et l'intégration à `AppShell`.

## 1. Prérequis backend (micro-ajustement — à faire d'abord)

Pour afficher les plugins **populaires quand la recherche est vide** (UX « à la VS Code »),
rendre le paramètre `q` **optionnel** sur `GET /api/plugins/search` :

- `q: str | None = Query(default=None, min_length=1)` (ou retirer la contrainte et valider à la main).
- Dans `OpenVsxClient.search`, si `query` est vide/`None`, **ne pas envoyer** la clé `query` à
  Open VSX (l'endpoint `/api/-/search` retourne alors le top trié par `sortBy`).
- Adapte la clé de cache pour gérer le cas sans requête (`query or ""`).
- Ajoute un test : `search()` sans `q` + `sort=popular` → renvoie une liste, et la requête mockée
  ne contient **pas** de param `query`.

Consigne ce changement dans `LESSONS.md` (le contrat `/search` accepte désormais `q` absent).

## 2. Objectif fonctionnel

Une page de navigation de plugins reproduisant l'essentiel de l'onglet Extensions de VS Code :

- barre de recherche (debouncée) ;
- sélecteur de tri : **Pertinence / Populaires / Récents / Mieux notés** ;
- liste paginée de cartes (icône, nom, éditeur, description courte, downloads, note) ;
- **fiche détail** (dialog) avec README rendu en markdown ;
- **sélection multiple** de plugins (toggle par carte), exposée via props pour réutilisation par
  le chantier « CRUD profils ». La page hôte affiche la liste des `id` sélectionnés
  (`namespace.name`), exactement ce qui ira dans `customizations.vscode.extensions`.

## 3. Décisions d'architecture (à respecter)

1. **Composant `PluginBrowser` contrôlé et réutilisable.** Il reçoit `selectedIds: Set<string>` et
   `onToggle(id: string)` en props. Aucune persistance ici ; la page hôte tient l'état local.
2. **README via `react-markdown` + `remark-gfm`, sans HTML brut.** Ne pas activer `rehype-raw`.
   Le contenu provient d'un tiers (Open VSX) → la sécurité prime sur le rendu exotique. Ajoute ces
   deux dépendances (et `@types` si nécessaire).
3. **Pagination via `useInfiniteQuery`** + bouton « Charger plus » (pas de scroll infini observé).
4. **Recherche debouncée** (300 ms) via un hook `useDebouncedValue`. Vide → on interroge quand même
   (landing « populaires »).
5. **Couche API isolée** dans `api/plugins.ts` ; si un client HTTP commun existe (`@/lib` /
   `@/shared`), passe par lui, sinon `fetch` typé avec gestion d'erreur. Les types TS reflètent les
   DTO backend.

## 4. Arborescence cible (adapter aux conventions réelles)

```
frontend/src/features/profiles/
  api/types.ts                    # types miroir des DTO backend
  api/plugins.ts                  # appels /api/plugins/*
  hooks/usePluginSearch.ts        # useInfiniteQuery
  hooks/usePluginDetail.ts        # useQuery détail
  hooks/usePluginReadme.ts        # useQuery readme (texte markdown)
  hooks/useDebouncedValue.ts
  components/PluginBrowser.tsx     # orchestration : search + sort + grille + pagination
  components/PluginSearchBar.tsx
  components/PluginSortSelect.tsx
  components/PluginCard.tsx
  components/PluginDetailDialog.tsx
  PluginBrowserPage.tsx            # page hôte (route), tient la sélection en local
  __tests__/PluginBrowser.test.tsx
```

## 5. Code de référence

### `api/types.ts`

```ts
export type PluginSort = 'relevance' | 'popular' | 'recent' | 'rating'

export interface PluginSummary {
  id: string            // "namespace.name" -> va dans customizations.vscode.extensions
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

### `api/plugins.ts`

```ts
import type { PluginDetail, PluginSearchResult, PluginSort } from './types'

export const PLUGINS_PAGE_SIZE = 24

export class PluginApiError extends Error {
  constructor(readonly status: number, readonly i18nKey: string) {
    super(i18nKey)
  }
}

async function getJson<T>(url: string, errorKey: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new PluginApiError(res.status, errorKey)
  return res.json() as Promise<T>
}

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
  if (params.q.trim()) qs.set('q', params.q.trim()) // vide -> populaires (backend q optionnel)
  return getJson(`/api/plugins/search?${qs}`, 'profiles.plugins.errors.search')
}

export function getPlugin(namespace: string, name: string): Promise<PluginDetail> {
  return getJson(
    `/api/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
    'profiles.plugins.errors.detail',
  )
}

export async function getPluginReadme(namespace: string, name: string): Promise<string> {
  const res = await fetch(
    `/api/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/readme`,
  )
  if (!res.ok) throw new PluginApiError(res.status, 'profiles.plugins.errors.readme')
  return res.text()
}
```

### `hooks/useDebouncedValue.ts`

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

### `hooks/usePluginSearch.ts`

```ts
import { useInfiniteQuery } from '@tanstack/react-query'
import { PLUGINS_PAGE_SIZE, searchPlugins } from '../api/plugins'
import type { PluginSort } from '../api/types'

export function usePluginSearch(query: string, sort: PluginSort) {
  return useInfiniteQuery({
    queryKey: ['plugins', 'search', query, sort],
    queryFn: ({ pageParam }) =>
      searchPlugins({ q: query, sort, offset: pageParam, size: PLUGINS_PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}
```

### `hooks/usePluginDetail.ts` et `usePluginReadme.ts`

```ts
// usePluginDetail.ts
import { useQuery } from '@tanstack/react-query'
import { getPlugin } from '../api/plugins'

export function usePluginDetail(namespace?: string, name?: string) {
  return useQuery({
    queryKey: ['plugins', 'detail', namespace, name],
    queryFn: () => getPlugin(namespace!, name!),
    enabled: Boolean(namespace && name),
  })
}

// usePluginReadme.ts
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

### `components/PluginBrowser.tsx` (orchestration)

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

      {isError && <p className="text-sm text-destructive">{t('profiles.plugins.errors.search')}</p>}
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
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
          <Button variant="outline" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
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

### `components/PluginDetailDialog.tsx` (README markdown)

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
            </DialogHeader>
            <p className="text-sm text-muted-foreground">{plugin.namespace} · {plugin.version}</p>
            <Button size="sm" variant={selected ? 'secondary' : 'default'} onClick={onToggle}>
              {t(selected ? 'profiles.plugins.remove' : 'profiles.plugins.add')}
            </Button>
            <div className="prose prose-sm prose-invert mt-4 max-w-none">
              {isLoading
                ? <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
                : <ReactMarkdown remarkPlugins={[remarkGfm]}>{readme ?? ''}</ReactMarkdown>}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

### `components/PluginCard.tsx`, `PluginSearchBar.tsx`, `PluginSortSelect.tsx`

Spécifications (mime le style des cartes existantes, composants shadcn) :

- **PluginCard** : carte cliquable (ouvre le détail au clic sur le corps). Icône (`icon_url`,
  fallback `lucide-react` `Puzzle`), `display_name`, `namespace`, description tronquée 2 lignes,
  `downloads` formatés (`Intl.NumberFormat`) + note. Un bouton/checkbox de **sélection** distinct
  (toggle), avec `stopPropagation` pour ne pas ouvrir le détail. État sélectionné visuellement
  marqué (bordure/`ring`). Accessible : carte focusable, action clavier (`Enter`).
- **PluginSearchBar** : `Input` shadcn avec icône `Search`, `placeholder` traduit, `aria-label`.
- **PluginSortSelect** : `Select` shadcn (Radix). Options = les 4 tris, libellés traduits. Valeur
  contrôlée.

### `PluginBrowserPage.tsx` (route de démonstration)

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
    <div className="flex flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">{t('profiles.plugins.title')}</h1>
      {selected.size > 0 && (
        <p className="text-sm text-muted-foreground">
          {t('profiles.plugins.selectedCount', { count: selected.size })} : {[...selected].join(', ')}
        </p>
      )}
      <PluginBrowser selectedIds={selected} onToggle={toggle} />
    </div>
  )
}
```

## 6. Intégration routing + navigation

- Dans `frontend/src/router.tsx`, ajoute (pattern lazy identique aux autres) :
  ```ts
  const PluginBrowserPage = lazy(() => import('@/features/profiles/PluginBrowserPage'))
  // dans children de AppShell :
  { path: '/profiles', element: <Wrap><PluginBrowserPage /></Wrap> },
  ```
- Ajoute l'entrée de navigation correspondante dans `AppShell` (même style d'item que Workspaces /
  Recipes), libellé traduit, icône `lucide-react` (`Puzzle` ou `SquareLibrary`).

## 7. i18n (clés à ajouter, fr + en)

```
profiles.plugins.title            "Plugins VSCode"
profiles.plugins.searchPlaceholder "Rechercher une extension…"
profiles.plugins.empty            "Aucun plugin trouvé."
profiles.plugins.loadMore         "Charger plus"
profiles.plugins.add              "Ajouter"
profiles.plugins.remove           "Retirer"
profiles.plugins.selectedCount    "{{count}} plugin sélectionné" / pluriel
profiles.plugins.sort.relevance|popular|recent|rating
profiles.plugins.errors.search|detail|readme
common.loading                    (réutilise l'existant si présent)
```

## 8. Tests (`vitest` + `@testing-library/react` + **MSW**)

Mets en place des handlers MSW pour `/api/plugins/search`, `/api/plugins/:ns/:name`,
`/api/plugins/:ns/:name/readme`. Cas attendus :

- rendu initial (query vide) → appelle `search` avec `sort=relevance`, affiche les cartes.
- saisie debouncée → après le délai, refetch avec la nouvelle `q`.
- changement de tri → nouvelle `queryKey`, refetch (vérifie via handler MSW que `sort` change).
- clic sur la sélection d'une carte → `onToggle` appelé, état visuel mis à jour.
- ouverture d'une carte → dialog visible, README markdown rendu (titre/heading présent).
- « Charger plus » visible quand `total > items.length`, masqué sinon.
- état d'erreur (handler 502) → message d'erreur traduit affiché.

Pas d'appel réseau réel. Respecte la config Vitest existante (`--maxWorkers=1`).

## 9. Definition of Done

- [ ] Micro-patch backend (`q` optionnel) livré + testé, consigné dans `LESSONS.md`.
- [ ] `PluginBrowser` contrôlé (`selectedIds` / `onToggle`), sans persistance.
- [ ] Recherche debouncée, 4 tris fonctionnels, landing « populaires » quand vide.
- [ ] Pagination `useInfiniteQuery` + « Charger plus ».
- [ ] Fiche détail (dialog) avec README markdown **sans HTML brut**.
- [ ] Toutes les chaînes via i18next (fr + en), aucune chaîne en dur.
- [ ] Route `/profiles` + item de navigation intégrés à `AppShell`.
- [ ] Tests verts (MSW), TypeScript strict sans `any` parasite, `eslint` propre.
- [ ] Aucun fichier > 300 lignes.
- [ ] Commits conventionnels FR sur `dev`.

## 10. Hors périmètre (chantier suivant)

Persistance des profils (YAML, partagé + fork par user), édition du `name`/`description` d'un
profil, génération du `devcontainer.json`. Le `PluginBrowser` est conçu pour être **embarqué** dans
l'éditeur de profil à ce moment-là — ne pas le coupler à une logique de sauvegarde ici.
