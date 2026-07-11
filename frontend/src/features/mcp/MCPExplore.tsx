import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Compass, ExternalLink, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSecrets } from '@/features/secrets/api'
import {
  type DiscoverySource,
  useCreateDiscoverySource,
  useDeleteDiscoverySource,
  useDiscoverySearch,
  useDiscoverySources,
  useProbeDiscoverySource,
} from './api'

/** Slug dérivé d'un label : minuscules, tirets, ASCII, borné à 63 caractères. */
function slugify(label: string): string {
  return label
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
}

/**
 * Bloc « MCP Explore » — configure les sources de découverte (instances
 * mcp-manager) : label, slug, URL, secret MCP_DISCOVERY, avec un bouton de test.
 * La recherche puis l'ajout de services viendront aux étapes suivantes.
 */
export default function MCPExplore() {
  const { t } = useTranslation()
  const { data: secrets = [] } = useSecrets('MCP_DISCOVERY')
  const { data: sources = [] } = useDiscoverySources()
  const create = useCreateDiscoverySource()
  const del = useDeleteDiscoverySource()
  const probe = useProbeDiscoverySource()

  const [label, setLabel] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [url, setUrl] = useState('')
  const [secretSlug, setSecretSlug] = useState('')

  const effectiveSlug = slugTouched ? slug : slugify(label)
  const canSubmit = label.trim() !== '' && effectiveSlug !== '' && url.trim() !== ''

  function onLabel(v: string) {
    setLabel(v)
    if (!slugTouched) setSlug(slugify(v))
  }

  function test() {
    probe.mutate(
      { url: url.trim(), secret_slug: secretSlug },
      {
        onSuccess: (r) =>
          toast.success(t('mcp.explore.testOk', { who: r.name || r.email || 'OK' })),
        onError: (e: Error) => toast.error(e.message),
      },
    )
  }

  function add() {
    create.mutate(
      { label: label.trim(), slug: effectiveSlug, url: url.trim(), secret_slug: secretSlug },
      {
        onSuccess: () => {
          toast.success(t('mcp.explore.added', { label: label.trim() }))
          setLabel('')
          setSlug('')
          setSlugTouched(false)
          setUrl('')
          setSecretSlug('')
        },
        onError: (e: Error) => toast.error(e.message),
      },
    )
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border bg-muted/40 p-5">
      <div className="flex items-center gap-2">
        <Compass className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">{t('mcp.explore.title')}</h2>
      </div>
      <p className="text-sm text-muted-foreground">{t('mcp.explore.subtitle')}</p>

      {/* Formulaire d'ajout de source */}
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          {t('mcp.explore.labelLabel')}
          <Input value={label} onChange={(e) => onLabel(e.target.value)} className="h-9" />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {t('mcp.explore.slugLabel')}
          <Input
            value={effectiveSlug}
            onChange={(e) => {
              setSlugTouched(true)
              setSlug(e.target.value)
            }}
            className="h-9 font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {t('mcp.explore.urlLabel')}
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('mcp.explore.urlPlaceholder')}
            className="h-9"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {t('mcp.explore.secretLabel')}
          <select
            value={secretSlug}
            onChange={(e) => setSecretSlug(e.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm"
          >
            <option value="">{t('mcp.explore.noSecret')}</option>
            {secrets.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={url.trim() === '' || probe.isPending}
          onClick={test}
        >
          {probe.isPending ? '…' : t('mcp.explore.test')}
        </Button>
        <Button size="sm" disabled={!canSubmit || create.isPending} onClick={add}>
          {t('mcp.explore.add')}
        </Button>
      </div>

      {/* Liste des sources configurées */}
      {sources.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            {t('mcp.explore.sourcesTitle')}
          </span>
          {sources.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm"
            >
              <span className="font-medium">{s.label}</span>
              <code className="truncate text-xs text-muted-foreground">{s.url}</code>
              <Button
                size="icon"
                variant="ghost"
                className="ml-auto h-6 w-6 text-destructive hover:text-destructive"
                onClick={() =>
                  del.mutate(s.id, {
                    onSuccess: () => toast.success(t('mcp.explore.deleted', { label: s.label })),
                    onError: (e: Error) => toast.error(e.message),
                  })
                }
                aria-label={t('mcp.explore.delete')}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <MCPSearch sources={sources} />
    </div>
  )
}

/** Transport affiché en badge court, robuste aux valeurs inconnues. */
function transportLabel(transport: string): string {
  return transport.replace(/_/g, ' ') || '—'
}

/**
 * Recherche dans le catalogue d'une source : sélecteur de source, champ de
 * requête, résultats paginés. Chaque résultat affiche nom, description,
 * transport, étoiles/statut du dépôt et les liens dépôt/doc. L'ajout comme
 * serveur MCP arrivera à l'étape 4.
 */
function MCPSearch({ sources }: { sources: DiscoverySource[] }) {
  const { t } = useTranslation()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)

  // Source effective dérivée : le choix explicite s'il est encore valide,
  // sinon la première source (auto-sélection sans effet de bord).
  const sourceId =
    selectedId !== null && sources.some((s) => s.id === selectedId)
      ? selectedId
      : (sources[0]?.id ?? null)

  const perPage = 10
  const search = useDiscoverySearch(sourceId, query, page, perPage)
  const result = search.data

  function submit() {
    setQuery(draft.trim())
    setPage(1)
  }

  if (sources.length === 0) return null

  const totalPages = result ? Math.max(1, Math.ceil(result.total / result.per_page)) : 1

  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{t('mcp.explore.searchTitle')}</h3>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        {sources.length > 1 && (
          <label className="flex flex-col gap-1 text-xs">
            {t('mcp.explore.sourceLabel')}
            <select
              value={sourceId ?? ''}
              onChange={(e) => {
                setSelectedId(Number(e.target.value))
                setQuery('')
                setDraft('')
                setPage(1)
              }}
              className="h-9 rounded-md border bg-background px-2 text-sm"
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder={t('mcp.explore.searchPlaceholder')}
          className="h-9 min-w-[12rem] flex-1"
        />
        <Button size="sm" disabled={draft.trim() === '' || search.isFetching} onClick={submit}>
          {search.isFetching ? t('mcp.explore.searching') : t('mcp.explore.searchBtn')}
        </Button>
      </div>

      {search.isError && (
        <p className="text-sm text-destructive">{(search.error as Error).message}</p>
      )}

      {result && !search.isFetching && result.items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.explore.noResults', { q: query })}</p>
      )}

      {result && result.items.length > 0 && (
        <>
          <span className="text-xs text-muted-foreground">
            {t('mcp.explore.resultsCount', { total: result.total })}
          </span>
          <ul className="flex flex-col gap-2">
            {result.items.map((it) => (
              <li
                key={it.id ?? it.name}
                className="flex flex-col gap-1 rounded-md border bg-background px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{it.name}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                    {transportLabel(it.transport)}
                  </span>
                  {it.repo_status && (
                    <span className="text-[10px] uppercase text-muted-foreground">
                      {it.repo_status}
                    </span>
                  )}
                  {it.stars > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {t('mcp.explore.stars', { count: it.stars })}
                    </span>
                  )}
                </div>
                {it.description && (
                  <p className="line-clamp-2 text-xs text-muted-foreground">{it.description}</p>
                )}
                <div className="flex gap-3 text-xs">
                  {it.source_url && (
                    <a
                      href={it.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" />
                      {t('mcp.explore.openRepo')}
                    </a>
                  )}
                  {it.doc_url && (
                    <a
                      href={it.doc_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" />
                      {t('mcp.explore.openDoc')}
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {totalPages > 1 && (
            <div className="flex items-center gap-3">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || search.isFetching}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                {t('mcp.explore.prev')}
              </Button>
              <span className="text-xs text-muted-foreground">
                {t('mcp.explore.pageOf', { page })} / {totalPages}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= totalPages || search.isFetching}
                onClick={() => setPage((p) => p + 1)}
              >
                {t('mcp.explore.next')}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
