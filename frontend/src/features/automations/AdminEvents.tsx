import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useEventTypes,
  useJournalEvents,
  useResetCursor,
  type JournalEvent,
} from './useAutomations'

function Row({ ev, onReplay }: { ev: JournalEvent; onReplay: (ev: JournalEvent) => void }) {
  const { t } = useTranslation()
  const subject = JSON.stringify(ev.subject)
  return (
    <div className="flex items-start gap-3 rounded-md border p-2 text-sm">
      <span
        className="shrink-0 font-mono text-xs font-semibold text-primary"
        title="seq (id de curseur)"
      >
        #{ev.seq}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <code className="rounded bg-muted px-1 py-0.5 text-xs">{ev.event_type}</code>
          <span className="text-xs text-muted-foreground">{ev.actor}</span>
          {ev.workspace && <Badge variant="outline">{ev.workspace}</Badge>}
          {ev.consumed_by && <Badge variant="secondary">consumed</Badge>}
          <span className="ml-auto text-xs text-muted-foreground">
            {new Date(ev.occurred_at).toLocaleString()}
          </span>
        </div>
        <div className="mt-1 truncate font-mono text-xs text-muted-foreground" title={subject}>
          {subject}
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">{ev.event_id}</div>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="shrink-0"
        onClick={() => onReplay(ev)}
        title={t('automations.events.replayHint')}
      >
        {t('automations.events.replayFromHere')}
      </Button>
    </div>
  )
}

export default function AdminEvents() {
  const { t } = useTranslation()
  const [filter, setFilter] = useState('')
  const eventTypes = useEventTypes()
  const resetCursor = useResetCursor()
  const { data, isLoading, isError } = useJournalEvents({ eventType: filter || undefined })

  function replay(ev: JournalEvent) {
    if (!confirm(t('automations.events.replayConfirm', { seq: ev.seq }))) return
    // Repositionne le curseur global juste avant cet event → il sera ré-évalué.
    resetCursor.mutate(ev.seq - 1, {
      onSuccess: (r) =>
        toast.success(t('automations.events.replayed', { automations: r.automations })),
    })
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-2 text-2xl font-semibold">{t('automations.events.title')}</h1>
      <p className="mb-4 text-sm text-muted-foreground">{t('automations.events.intro')}</p>

      <div className="mb-4 flex items-center gap-2">
        <label className="text-sm text-muted-foreground" htmlFor="ev-filter">
          {t('automations.events.filter')}
        </label>
        <select
          id="ev-filter"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">{t('automations.events.allTypes')}</option>
          {eventTypes.data?.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('automations.events.empty')}</p>
      )}

      <div className="flex flex-col gap-2">
        {data?.map((ev) => (
          <Row key={ev.seq} ev={ev} onReplay={replay} />
        ))}
      </div>
    </div>
  )
}
