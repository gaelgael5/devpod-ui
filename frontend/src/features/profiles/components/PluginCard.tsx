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
          aria-label={t(selected ? 'profiles.plugins.remove' : 'profiles.plugins.add')}
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
