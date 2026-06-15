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
