import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Play, RotateCw, ScrollText, Square, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { STATUS_TONE_CLASS } from '@/features/workspaces/statusTone'
import { useDeploymentAction, useDeleteDeployment, useDeploymentLogs } from '../hooks/useCompose'
import type { ComposeDeployment, DeploymentStatus } from '../api/types'

const COMPOSE_STATUS_CLASS: Record<DeploymentStatus, string> = {
  running: STATUS_TONE_CLASS.running,
  partial: STATUS_TONE_CLASS.progress,
  stopped: STATUS_TONE_CLASS.stopped,
  error: STATUS_TONE_CLASS.error,
  created: STATUS_TONE_CLASS.neutral,
}

function DeploymentLogsDialog({
  uid,
  id,
  open,
  onOpenChange,
}: {
  uid: string
  id: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { t } = useTranslation()
  const { data, isLoading } = useDeploymentLogs(uid, open)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('compose.logs.title', { id })}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-auto rounded-md bg-black p-3 font-mono text-xs text-green-400 min-h-[200px]">
          {isLoading && <span className="text-muted-foreground">{t('compose.logs.loading')}</span>}
          {!isLoading && !data?.output && <span className="text-muted-foreground">{t('compose.logs.empty')}</span>}
          {data?.output && <pre className="whitespace-pre-wrap break-words">{data.output}</pre>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Ligne d'un déploiement compose : statut, ports, actions start/stop/restart/logs/delete.
 *  `readOnly` (ex. VM partagée-vers ce workspace) masque toutes les actions. */
export default function DeploymentRow({
  dep,
  readOnly = false,
}: {
  dep: ComposeDeployment
  readOnly?: boolean
}) {
  const { t } = useTranslation()
  const action = useDeploymentAction()
  const del = useDeleteDeployment()
  const pending = action.isPending || del.isPending
  const [logsOpen, setLogsOpen] = useState(false)

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap rounded-md border bg-muted/40 px-3 py-2 text-sm">
        <span className="font-mono text-xs font-medium flex-1 min-w-0 truncate">{dep.id}</span>
        <Badge variant="outline" className={cn('text-xs shrink-0', COMPOSE_STATUS_CLASS[dep.status])}>
          {t(`compose.status.${dep.status}`)}
        </Badge>
        {dep.host_ports.length > 0 && (
          <span className="text-xs text-muted-foreground shrink-0">
            :{dep.host_ports.join(', :')}
          </span>
        )}
        {!readOnly && (
        <div className="flex gap-1 shrink-0">
          {dep.status === 'stopped' ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0"
              disabled={pending}
              onClick={() => action.mutate({ uid: dep.uid, action: 'start' })}
              aria-label={t('compose.actions.start')}
            >
              <Play className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0"
              disabled={pending}
              onClick={() => action.mutate({ uid: dep.uid, action: 'stop' })}
              aria-label={t('compose.actions.stop')}
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0"
            disabled={pending}
            onClick={() => action.mutate({ uid: dep.uid, action: 'restart' })}
            aria-label={t('compose.actions.restart')}
          >
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0"
            onClick={() => setLogsOpen(true)}
            aria-label={t('compose.logs.button')}
          >
            <ScrollText className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-destructive hover:text-destructive"
            disabled={pending}
            onClick={() => del.mutate(dep.uid)}
            aria-label={t('compose.actions.down')}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
        )}
      </div>
      <DeploymentLogsDialog uid={dep.uid} id={dep.id} open={logsOpen} onOpenChange={setLogsOpen} />
    </>
  )
}
