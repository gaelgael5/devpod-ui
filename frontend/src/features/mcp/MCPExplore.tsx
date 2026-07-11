import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Compass, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSecrets } from '@/features/secrets/api'
import {
  useCreateDiscoverySource,
  useDeleteDiscoverySource,
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
    </div>
  )
}
