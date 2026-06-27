import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useDeployments, useDeploymentAction, useDeleteDeployment } from '../hooks/useCompose'
import type { ComposeDeployment, DeploymentStatus } from '../api/types'
import LogsDialog from './LogsDialog'

function statusVariant(
  status: DeploymentStatus,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'running':
      return 'default'
    case 'partial':
      return 'secondary'
    case 'error':
      return 'destructive'
    default:
      return 'outline'
  }
}

interface RowProps {
  deployment: ComposeDeployment
  onAction: (action: 'stop' | 'start' | 'restart') => void
  isPending: boolean
  onDelete: () => void
  onLogs: () => void
}

function DeploymentRow({ deployment, onAction, isPending, onDelete, onLogs }: RowProps) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border bg-card p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium">{deployment.id}</span>
        <Badge variant={statusVariant(deployment.status)}>
          {t(`compose.status.${deployment.status}`)}
        </Badge>
        <span className="text-xs text-muted-foreground">{deployment.node_id}</span>
        {deployment.host_ports.length > 0 && (
          <span className="text-xs text-muted-foreground">
            ports: {deployment.host_ports.join(', ')}
          </span>
        )}
      </div>
      <div className="flex gap-2 flex-wrap">
        <Button size="sm" variant="outline" disabled={isPending} onClick={() => onAction('start')}>
          {t('compose.actions.start')}
        </Button>
        <Button size="sm" variant="outline" disabled={isPending} onClick={() => onAction('stop')}>
          {t('compose.actions.stop')}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={isPending}
          onClick={() => onAction('restart')}
        >
          {t('compose.actions.restart')}
        </Button>
        <Button size="sm" variant="ghost" onClick={onLogs}>
          {t('compose.actions.logs')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
        >
          {t('compose.actions.down')}
        </Button>
      </div>
    </div>
  )
}

export default function DeploymentsPanel() {
  const { t } = useTranslation()
  const { data: deployments = [], isLoading } = useDeployments()
  const action = useDeploymentAction()
  const del = useDeleteDeployment()
  const [deleteTarget, setDeleteTarget] = useState<ComposeDeployment | null>(null)
  const [logsTarget, setLogsTarget] = useState<string | null>(null)

  if (isLoading) {
    return <p className="text-sm text-muted-foreground mt-4">{t('common.loading')}</p>
  }

  if (deployments.length === 0) {
    return (
      <p className="text-sm text-muted-foreground mt-4">{t('compose.empty.deployments')}</p>
    )
  }

  return (
    <div className="flex flex-col gap-3 mt-4">
      {deployments.map((dep) => (
        <DeploymentRow
          key={dep.id}
          deployment={dep}
          onAction={(act) => action.mutate({ id: dep.id, action: act })}
          isPending={action.isPending}
          onDelete={() => setDeleteTarget(dep)}
          onLogs={() => setLogsTarget(dep.id)}
        />
      ))}

      <Dialog
        open={Boolean(deleteTarget)}
        onOpenChange={(o) => {
          if (!o) setDeleteTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('compose.delete.confirm')}</DialogTitle>
            <DialogDescription>{deleteTarget?.id}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t('compose.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={del.isPending}
              onClick={() => {
                if (!deleteTarget) return
                del.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })
              }}
            >
              {t('compose.delete.ok')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {logsTarget && (
        <LogsDialog
          deploymentId={logsTarget}
          open={true}
          onOpenChange={(o) => {
            if (!o) setLogsTarget(null)
          }}
        />
      )}
    </div>
  )
}
