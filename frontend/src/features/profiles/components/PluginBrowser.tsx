import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
  const [showSelected, setShowSelected] = useState(false)
  const [summaryCache, setSummaryCache] = useState<Map<string, PluginSummary>>(new Map())

  const query = useDebouncedValue(rawQuery, 300)

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    usePluginSearch(query, sort)

  const items = useMemo(() => data?.pages.flatMap((p) => p.items) ?? [], [data])

  // Alimente le cache à chaque page de résultats chargée
  useEffect(() => {
    if (!items.length) return
    setSummaryCache((prev) => {
      const next = new Map(prev)
      items.forEach((p) => next.set(p.id, p))
      return next
    })
  }, [items])

  const { knownSelected, unknownSelectedIds } = useMemo(() => {
    const known: PluginSummary[] = []
    const unknown: string[] = []
    for (const id of selectedIds) {
      const summary = summaryCache.get(id)
      if (summary) known.push(summary)
      else unknown.push(id)
    }
    return { knownSelected: known, unknownSelectedIds: unknown }
  }, [selectedIds, summaryCache])

  if (showSelected) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t('profiles.plugins.selectedCount', { count: selectedIds.size })}
          </span>
          <Button size="sm" variant="outline" onClick={() => setShowSelected(false)}>
            {t('profiles.plugins.showAll')}
          </Button>
        </div>

        {selectedIds.size === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('profiles.plugins.selectedEmpty')}
          </p>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {knownSelected.map((p) => (
            <PluginCard
              key={p.id}
              plugin={p}
              selected={true}
              onToggle={() => onToggle(p.id)}
              onOpen={() => setOpened(p)}
            />
          ))}
        </div>

        {unknownSelectedIds.length > 0 && (
          <div className="flex flex-col gap-1">
            {unknownSelectedIds.map((id) => (
              <div
                key={id}
                className="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <span className="text-sm font-mono text-muted-foreground">{id}</span>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => onToggle(id)}
                  aria-label={t('profiles.plugins.remove')}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <PluginSearchBar value={rawQuery} onChange={setRawQuery} />
        <PluginSortSelect value={sort} onChange={setSort} />
        <Button
          size="sm"
          variant="outline"
          onClick={() => setShowSelected(true)}
          className="shrink-0"
        >
          {t('profiles.plugins.showSelected')}
          {selectedIds.size > 0 && (
            <Badge variant="secondary" className="ml-1.5">
              {selectedIds.size}
            </Badge>
          )}
        </Button>
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
