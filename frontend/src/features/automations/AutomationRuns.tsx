import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useClearRuns, useReplayRun, useRuns, type Run, type TraceItem } from './useAutomations'

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' {
  if (status === 'ok') return 'default'
  if (status === 'failed') return 'destructive'
  return 'secondary'
}

function TraceView({ trace }: { trace: TraceItem[] }) {
  const { t } = useTranslation()
  return (
    <details className="mt-1">
      <summary className="cursor-pointer select-none text-xs text-muted-foreground">
        {t('automations.runs.trace', { n: trace.length })}
      </summary>
      <div className="mt-1 flex flex-col gap-1">
        {trace.map((item, i) => {
          const okish = item.status === 'ok' || item.passed === true
          const koish = item.status === 'failed' || item.passed === false
          return (
            <div key={i} className="rounded border bg-muted/30 p-1.5 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <code className="text-muted-foreground">{item.path}</code>
                <Badge variant="outline">{item.kind}</Badge>
                {item.name && <code>{item.name}</code>}
                {item.op && <code>{item.op}</code>}
                {item.http_status != null && (
                  <span className="text-muted-foreground">HTTP {item.http_status}</span>
                )}
                {okish && <span className="text-green-600">✓</span>}
                {koish && <span className="text-destructive">✗</span>}
              </div>
              {item.preview && (
                <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap font-mono">
                  {item.preview}
                </pre>
              )}
              {item.detail && (
                <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap font-mono text-muted-foreground">
                  {item.detail}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </details>
  )
}

function RunRow({ automationId, run }: { automationId: string; run: Run }) {
  const { t } = useTranslation()
  const replay = useReplayRun()
  return (
    <div className="border-b py-2 text-sm last:border-0">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
          {run.http_status != null && (
            <span className="text-xs text-muted-foreground">HTTP {run.http_status}</span>
          )}
          {run.manual && <Badge variant="secondary">{t('automations.runs.manual')}</Badge>}
          <code className="text-xs text-muted-foreground">seq {run.event_seq}</code>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            replay.mutate(
              { automationId, runId: run.id },
              { onSuccess: () => toast.success(t('automations.runs.replayed')) },
            )
          }
          disabled={replay.isPending}
        >
          {t('automations.runs.replay')}
        </Button>
      </div>
      {run.error && <p className="mt-1 text-xs text-destructive">{run.error}</p>}
      {run.request_preview && (
        <pre className="mt-1 max-h-24 overflow-auto rounded bg-muted/50 p-2 text-xs">
          {run.request_preview}
        </pre>
      )}
      {run.trace && run.trace.length > 0 && <TraceView trace={run.trace} />}
    </div>
  )
}

export function AutomationRuns({
  automationId,
  label,
  open,
  onOpenChange,
}: {
  automationId: string
  label: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { t } = useTranslation()
  const { data, isLoading } = useRuns(open ? automationId : null)
  const clear = useClearRuns()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('automations.runs.title', { label })}</DialogTitle>
        </DialogHeader>
        <div className="mb-2 flex justify-end">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              clear.mutate(automationId, {
                onSuccess: () => toast.success(t('automations.runs.cleared')),
              })
            }
            disabled={clear.isPending || !data?.length}
          >
            {t('automations.runs.clear')}
          </Button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {isLoading && <p className="text-sm text-muted-foreground">…</p>}
          {data && data.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('automations.runs.empty')}</p>
          )}
          {data?.map((run) => (
            <RunRow key={run.id} automationId={automationId} run={run} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
