import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Key } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { WorkspaceSpec, WorkspaceStatus, WorkspaceStatusValue } from './types'
import SshKeyDialog from './SshKeyDialog'
import LogDialog from './LogDialog'

const STATUS_CLASS: Record<WorkspaceStatusValue, string> = {
  running: 'bg-green-500/10 text-green-600 border-green-500/30',
  stopped: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30',
  provisioning: 'bg-primary/10 text-primary border-primary/30',
  failed: 'bg-destructive/10 text-destructive border-destructive/30',
  unknown: 'bg-muted text-muted-foreground border-border',
}

interface Props {
  spec: WorkspaceSpec
  status: WorkspaceStatus
  onStop: (name: string) => void
  onDelete: (name: string) => void
  onStart?: (name: string) => void
}

export default function WorkspaceCard({ spec, status, onStop, onDelete, onStart }: Props) {
  const { t } = useTranslation()
  const [sshKeyOpen, setSshKeyOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const s = status.status

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-foreground">{spec.name}</div>
          <div className="text-xs text-muted-foreground">{spec.source}</div>
        </div>
        <Badge
          variant="outline"
          className={cn('shrink-0 text-xs', STATUS_CLASS[s])}
        >
          {s === 'provisioning' && '⟳ '}{t(`workspaces.status.${s}`)}
        </Badge>
      </div>

      {spec.recipes.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {spec.recipes.map((r) => (
            <span
              key={r}
              className="rounded-sm bg-primary/10 px-2 py-0.5 text-xs text-primary"
            >
              {r}
            </span>
          ))}
        </div>
      )}

      {s === 'provisioning' && (
        <div className="mb-3 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
        </div>
      )}

      <div className="flex gap-2">
        {s === 'running' && status.url && (
          <Button size="sm" asChild>
            <a href={status.url} target="_blank" rel="noopener noreferrer">
              {t('workspaces.actions.open')}
            </a>
          </Button>
        )}
        {s === 'running' && (
          <Button size="sm" variant="outline" onClick={() => onStop(spec.name)}>
            {t('workspaces.actions.stop')}
          </Button>
        )}
        {s === 'stopped' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart}
          >
            {t('workspaces.actions.start')}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed') && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setConfirmOpen(true)}
          >
            {t('workspaces.actions.delete')}
          </Button>
        )}
        {s === 'failed' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart}
          >
            {t('workspaces.actions.retry')}
          </Button>
        )}
        {spec.ssh_key && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSshKeyOpen(true)}
            aria-label={t('workspaces.sshKey.button')}
          >
            <Key className="h-4 w-4" />
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setLogsOpen(true)}
          aria-label={t('workspaces.logs.button')}
        >
          <FileText className="h-4 w-4" />
        </Button>
      </div>

      {spec.ssh_key && (
        <SshKeyDialog
          workspaceName={spec.name}
          open={sshKeyOpen}
          onOpenChange={setSshKeyOpen}
        />
      )}
      <LogDialog
        workspaceName={spec.name}
        open={logsOpen}
        onOpenChange={setLogsOpen}
      />
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.confirm.deleteTitle')}</DialogTitle>
            <DialogDescription className="space-y-2">
              {t('workspaces.confirm.deleteDescription', { name: spec.name })}
              {' '}
              {t('workspaces.confirm.deleteShelveHint')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setConfirmOpen(false)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setConfirmOpen(false)
                onDelete(spec.name)
              }}
            >
              {t('workspaces.confirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
