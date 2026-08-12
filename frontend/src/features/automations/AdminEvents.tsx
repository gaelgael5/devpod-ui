import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useEventTypes,
  useJournalEvents,
  useResetCursor,
  type JournalEvent,
} from './useAutomations'

const PAGE_SIZES = [50, 100, 150]

// Arbre de filtre : événements groupés par domaine (séparateur « . »). Cocher un
// domaine coche/décoche tous ses types (case tri-état : indeterminate = partiel).
function EventTypeFilter({
  codes,
  selected,
  onChange,
}: {
  codes: string[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const { t } = useTranslation()
  const groups = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const code of codes) {
      const domain = code.includes('.') ? code.split('.')[0] : 'autre'
      m.set(domain, [...(m.get(domain) ?? []), code])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [codes])

  const sel = new Set(selected)
  const toggleOne = (code: string) => {
    const next = new Set(sel)
    if (next.has(code)) next.delete(code)
    else next.add(code)
    onChange([...next])
  }
  const toggleDomain = (members: string[], allOn: boolean) => {
    const next = new Set(sel)
    for (const m of members) {
      if (allOn) next.delete(m)
      else next.add(m)
    }
    onChange([...next])
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">{t('automations.events.filter')}</span>
        {selected.length > 0 && (
          <>
            <Badge variant="secondary">
              {t('automations.events.selectedCount', { n: selected.length })}
            </Badge>
            <button
              type="button"
              className="text-xs text-muted-foreground hover:underline"
              onClick={() => onChange([])}
            >
              {t('automations.events.filterNone')}
            </button>
          </>
        )}
      </div>
      <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border p-2">
        {groups.map(([domain, members]) => {
          const on = members.filter((m) => sel.has(m)).length
          const allOn = on === members.length
          return (
            <details key={domain} open={on > 0} className="group">
              <summary className="flex cursor-pointer select-none items-center gap-2 text-xs font-semibold text-muted-foreground">
                <input
                  type="checkbox"
                  checked={allOn}
                  ref={(el) => {
                    if (el) el.indeterminate = on > 0 && !allOn
                  }}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggleDomain(members, allOn)}
                />
                {domain}
                {on > 0 && <span className="text-primary">({on})</span>}
              </summary>
              <div className="ml-5 mt-1 space-y-1 border-l pl-3">
                {members.map((code) => (
                  <label key={code} className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={sel.has(code)}
                      onChange={() => toggleOne(code)}
                    />
                    <span className="font-mono text-xs">{code}</span>
                  </label>
                ))}
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}

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
  const [filter, setFilter] = useState<string[]>([])
  const [pageSize, setPageSize] = useState(50)
  // Pile de curseurs `before_seq` : cursors[i] = borne de la page i (undefined = page 0).
  const [cursors, setCursors] = useState<(number | undefined)[]>([undefined])
  const page = cursors.length - 1
  const beforeSeq = cursors[page]

  const eventTypes = useEventTypes()
  const resetCursor = useResetCursor()
  const { data, isLoading, isError } = useJournalEvents({
    eventTypes: filter,
    beforeSeq,
    limit: pageSize,
  })

  // Tout changement de filtre/taille rembobine à la première page.
  function applyFilter(next: string[]) {
    setFilter(next)
    setCursors([undefined])
  }
  function applyPageSize(n: number) {
    setPageSize(n)
    setCursors([undefined])
  }
  function nextPage() {
    if (data && data.length === pageSize) setCursors((c) => [...c, data[data.length - 1].seq])
  }
  function prevPage() {
    setCursors((c) => (c.length > 1 ? c.slice(0, -1) : c))
  }

  function replay(ev: JournalEvent) {
    if (!confirm(t('automations.events.replayConfirm', { seq: ev.seq }))) return
    // Repositionne le curseur global juste avant cet event → il sera ré-évalué.
    resetCursor.mutate(ev.seq - 1, {
      onSuccess: (r) =>
        toast.success(t('automations.events.replayed', { automations: r.automations })),
    })
  }

  const hasNext = !!data && data.length === pageSize

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('automations.events.title')}</h1>
        <Link to="/admin/automations" className="text-sm text-muted-foreground hover:underline">
          ← {t('automations.title')}
        </Link>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">{t('automations.events.intro')}</p>

      <div className="mb-4">
        <EventTypeFilter codes={eventTypes.data ?? []} selected={filter} onChange={applyFilter} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground" htmlFor="ev-size">
          {t('automations.events.pageSize')}
          <select
            id="ev-size"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={pageSize}
            onChange={(e) => applyPageSize(Number(e.target.value))}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={prevPage} disabled={page === 0}>
            {t('automations.events.prev')}
          </Button>
          <span className="text-xs text-muted-foreground">
            {t('automations.events.page', { n: page + 1 })}
          </span>
          <Button variant="outline" size="sm" onClick={nextPage} disabled={!hasNext}>
            {t('automations.events.next')}
          </Button>
        </div>
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
