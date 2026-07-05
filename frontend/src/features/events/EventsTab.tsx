import { useTranslation } from 'react-i18next'
import { RefreshCw, RotateCcw, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useAppEvents, useReplayEvent, type AppEventDelivery, type AppEventEntry,
} from './api'

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(iso))
}

/** Dernière livraison par écouteur (l'historique des rejeux est ordonné par id). */
function latestDeliveries(deliveries: AppEventDelivery[]): AppEventDelivery[] {
  const byListener = new Map<string, AppEventDelivery>()
  for (const d of deliveries) byListener.set(d.listener, d)
  return [...byListener.values()]
}

function subjectSummary(subject: Record<string, unknown>): string {
  return Object.entries(subject)
    .filter(([, v]) => v !== null && v !== '' && v !== undefined)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join('  ')
}

function EventCard({ event }: { event: AppEventEntry }) {
  const { t } = useTranslation()
  const replay = useReplayEvent()
  const deliveries = latestDeliveries(event.deliveries)
  const summary = subjectSummary(event.subject)

  return (
    <div className="flex items-start gap-3 rounded-lg border bg-card p-4">
      <Zap className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="text-xs font-mono">{event.type}</Badge>
          {event.workspace && (
            <span className="text-sm">
              {t('appEvents.workspaceLabel')} <span className="font-medium">{event.workspace}</span>
            </span>
          )}
          <span className="text-xs text-muted-foreground">{fmtDate(event.occurred_at)}</span>
        </div>
        {summary && (
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{summary}</p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {deliveries.length === 0 && (
            <span className="text-xs text-muted-foreground">{t('appEvents.noListener')}</span>
          )}
          {deliveries.map((d) => (
            <Badge
              key={d.listener}
              variant={d.status === 'ok' ? 'secondary' : 'destructive'}
              className="text-xs"
              title={d.error ?? undefined}
            >
              {d.listener}: {d.status}
            </Badge>
          ))}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="shrink-0"
        disabled={replay.isPending}
        title={t('appEvents.replay')}
        onClick={() =>
          replay.mutate(event.id, {
            onSuccess: () => toast.success(t('appEvents.replayRequested')),
            onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
          })
        }
      >
        <RotateCcw className="h-3.5 w-3.5" />
        <span className="ml-1">{t('appEvents.replay')}</span>
      </Button>
    </div>
  )
}

export default function EventsTab() {
  const { t } = useTranslation()
  const { data: events = [], isLoading, refetch, isFetching } = useAppEvents()

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('appEvents.sectionTitle')}</h2>
        <Button size="sm" variant="outline" disabled={isFetching} onClick={() => refetch()}>
          <RefreshCw className="mr-1 h-4 w-4" />{t('appEvents.refresh')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && events.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('appEvents.empty')}</p>
      )}
      <div className="flex flex-col gap-2">
        {events.map((e) => (
          <EventCard key={e.id} event={e} />
        ))}
      </div>
    </div>
  )
}
