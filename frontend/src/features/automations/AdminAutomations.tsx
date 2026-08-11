import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { AutomationRuns } from './AutomationRuns'
import { treeSummary } from './tree'
import {
  useAutomations,
  useBackfill,
  useDeleteAutomation,
  useInjectTestEvent,
  useReorderAutomations,
  useUpdateAutomation,
  type Automation,
} from './useAutomations'

function SimulateBar() {
  const { t } = useTranslation()
  const inject = useInjectTestEvent()
  const backfill = useBackfill()

  function fire(kind: 'user' | 'host' | 'workspace' | 'session') {
    inject.mutate(
      { kind },
      { onSuccess: (r) => toast.success(t('automations.sim.injected', { code: r.emitted })) },
    )
  }

  return (
    <div className="mb-6 flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 p-3">
      <span className="text-sm font-medium">{t('automations.sim.title')}</span>
      <Button variant="outline" size="sm" onClick={() => fire('user')} disabled={inject.isPending}>
        {t('automations.sim.user')}
      </Button>
      <Button variant="outline" size="sm" onClick={() => fire('host')} disabled={inject.isPending}>
        {t('automations.sim.host')}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => fire('workspace')}
        disabled={inject.isPending}
      >
        {t('automations.sim.workspace')}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => fire('session')}
        disabled={inject.isPending}
      >
        {t('automations.sim.session')}
      </Button>
      <div className="ml-auto">
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            backfill.mutate(undefined, {
              onSuccess: (r) =>
                toast.success(
                  t('automations.sim.backfilled', {
                    users: r.users,
                    hosts: r.hosts,
                    workspaces: r.workspaces,
                    sessions: r.sessions,
                  }),
                ),
            })
          }
          disabled={backfill.isPending}
        >
          {backfill.isPending ? '…' : t('automations.sim.backfill')}
        </Button>
      </div>
    </div>
  )
}

function Row({
  automation,
  index,
  total,
  onEdit,
  onRuns,
  onMove,
}: {
  automation: Automation
  index: number
  total: number
  onEdit: (a: Automation) => void
  onRuns: (a: Automation) => void
  onMove: (index: number, dir: -1 | 1) => void
}) {
  const { t } = useTranslation()
  const update = useUpdateAutomation()
  const del = useDeleteAutomation()

  return (
    <div className="flex items-start justify-between gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-0.5">
        <Button
          variant="ghost"
          size="sm"
          className="h-5 px-1"
          onClick={() => onMove(index, -1)}
          disabled={index === 0}
        >
          ▲
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-5 px-1"
          onClick={() => onMove(index, 1)}
          disabled={index === total - 1}
        >
          ▼
        </Button>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{automation.label}</span>
          {automation.stop_chain && <Badge variant="outline">stop_chain</Badge>}
          {automation.pending > 0 && (
            <Badge>{t('automations.pending', { n: automation.pending })}</Badge>
          )}
          <Badge variant="outline" title={t('automations.cursorHint')}>
            {t('automations.cursor', { seq: automation.last_seq })}
          </Badge>
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {automation.event_types.map((e) => (
            <code key={e} className="rounded bg-muted px-1 py-0.5 text-xs">
              {e}
            </code>
          ))}
        </div>
        <div className="mt-1 truncate text-xs text-muted-foreground">
          {(() => {
            const s = treeSummary(automation.tree)
            return t('automations.tree.summary', { blocks: s.blocks, calls: s.calls })
          })()}
        </div>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-2">
        <label className="flex items-center gap-2 text-xs">
          {t('automations.form.active')}
          <Switch
            checked={automation.active}
            onCheckedChange={(v) =>
              update.mutate({ id: automation.id, body: { active: v } })
            }
          />
        </label>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => onRuns(automation)}>
            {t('automations.runsBtn')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onEdit(automation)}>
            {t('common.edit')}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              if (confirm(t('automations.confirmDelete', { label: automation.label }))) {
                del.mutate(automation.id, {
                  onSuccess: () => toast.success(t('automations.deleted')),
                })
              }
            }}
          >
            {t('common.delete')}
          </Button>
        </div>
      </div>
    </div>
  )
}

export default function AdminAutomations() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data, isLoading, isError } = useAutomations()
  const reorder = useReorderAutomations()
  const [runsFor, setRunsFor] = useState<Automation | null>(null)

  // Édition en page pleine (la popup historique est retirée).
  function openNew() {
    navigate('/admin/automations/new')
  }
  function openEdit(a: Automation) {
    navigate(`/admin/automations/${a.id}`)
  }
  function move(index: number, dir: -1 | 1) {
    if (!data) return
    const ids = data.map((a) => a.id)
    const j = index + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    reorder.mutate(ids)
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('automations.title')}</h1>
        <Button onClick={openNew}>{t('automations.new')}</Button>
      </div>
      <p className="mb-6 text-sm text-muted-foreground">{t('automations.intro')}</p>

      <SimulateBar />

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('automations.empty')}</p>
      )}

      <div className="flex flex-col gap-2">
        {data?.map((a, i) => (
          <Row
            key={a.id}
            automation={a}
            index={i}
            total={data.length}
            onEdit={openEdit}
            onRuns={setRunsFor}
            onMove={move}
          />
        ))}
      </div>

      {runsFor && (
        <AutomationRuns
          automationId={runsFor.id}
          label={runsFor.label}
          open={runsFor !== null}
          onOpenChange={(v) => !v && setRunsFor(null)}
        />
      )}
    </div>
  )
}
