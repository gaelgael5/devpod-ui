import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, MessageSquare } from 'lucide-react'
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
import {
  useDeployments,
  useDeploymentAction,
  useDeleteDeployment,
  useDeploymentMessage,
} from '../hooks/useCompose'
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

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <Button size="sm" variant="outline" onClick={handleCopy} className="shrink-0 gap-1.5">
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('workspaces.messages.copied') : t('workspaces.messages.copy')}
    </Button>
  )
}

function DeploymentMessageDialog({
  uid,
  open,
  onOpenChange,
}: {
  uid: string
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const { t } = useTranslation()
  const { data: msg, isLoading, isError } = useDeploymentMessage(uid, open)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('compose.message.title')}</DialogTitle>
          <DialogDescription className="sr-only">
            {t('compose.message.description')}
          </DialogDescription>
        </DialogHeader>
        {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
        {isError && (
          <p className="text-sm text-muted-foreground">{t('compose.message.none')}</p>
        )}
        {msg && (
          <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/40 p-3">
              <pre className="flex-1 whitespace-pre-wrap text-sm font-mono">{msg.message}</pre>
              <CopyButton text={msg.message} />
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('common.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface RowProps {
  deployment: ComposeDeployment
  onAction: (action: 'stop' | 'start' | 'restart') => void
  isPending: boolean
  onDelete: () => void
  onLogs: () => void
  onMessage: () => void
}

function DeploymentRow({ deployment, onAction, isPending, onDelete, onLogs, onMessage }: RowProps) {
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
            :{deployment.host_ports.join(', :')}
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
        {deployment.message_id != null && (
          <Button size="sm" variant="ghost" onClick={onMessage} className="gap-1.5">
            <MessageSquare className="h-3.5 w-3.5" />
          </Button>
        )}
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
  const [msgTarget, setMsgTarget] = useState<string | null>(null)

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
          key={dep.uid}
          deployment={dep}
          onAction={(act) => action.mutate({ uid: dep.uid, action: act })}
          isPending={action.isPending}
          onDelete={() => setDeleteTarget(dep)}
          onLogs={() => setLogsTarget(dep.uid)}
          onMessage={() => setMsgTarget(dep.uid)}
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
                del.mutate(deleteTarget.uid, { onSuccess: () => setDeleteTarget(null) })
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

      {msgTarget && (
        <DeploymentMessageDialog
          uid={msgTarget}
          open={true}
          onOpenChange={(o) => {
            if (!o) setMsgTarget(null)
          }}
        />
      )}
    </div>
  )
}
