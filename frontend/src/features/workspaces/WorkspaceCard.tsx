import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FileText, Key, Loader2 } from 'lucide-react'
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
import WorkspaceSshTerminalWindow from './WorkspaceSshTerminalWindow'
import InitializersMenu from './InitializersMenu'
import AddTestVmDialog from './AddTestVmDialog'

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
  onDelete: (name: string, shelve: boolean) => void
  onStart?: (name: string) => void
  onRecreate?: (name: string) => void
  isStarting?: boolean
}

export default function WorkspaceCard({ spec, status, onStop, onDelete, onStart, onRecreate, isStarting = false }: Props) {
  const { t } = useTranslation()
  const [sshKeyOpen, setSshKeyOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [recreateOpen, setRecreateOpen] = useState(false)
  const [shellOpen, setShellOpen] = useState(false)
  const [addVmOpen, setAddVmOpen] = useState(false)
  const s = status.status

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-foreground">{spec.name}</div>
          <div className="text-xs text-muted-foreground">{spec.source}</div>
          {spec.host && (
            <div className="text-xs text-muted-foreground/70 font-mono">{spec.host}</div>
          )}
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

      {(s === 'provisioning' || isStarting) && (
        <div className="mb-3 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
        </div>
      )}

      <div className="flex gap-2">
        {s === 'running' && status.url && (
          <Button size="sm" asChild>
            <a href={status.url} target="_blank" rel="noopener noreferrer">
              {t('workspaces.actions.openVscode')}
            </a>
          </Button>
        )}
        {s === 'running' && (
          <Button size="sm" variant="outline" onClick={() => onStop(spec.name)}>
            {t('workspaces.actions.stop')}
          </Button>
        )}
        {s === 'running' && (
          <Button size="sm" variant="outline" asChild>
            <Link to={`/workspaces/${spec.name}/terminals`}>
              {t('workspaces.terminals.open')}
            </Link>
          </Button>
        )}
        {s === 'stopped' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart || isStarting}
          >
            {isStarting && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            {t('workspaces.actions.start')}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed') && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRecreateOpen(true)}
            disabled={!onRecreate}
          >
            {t('workspaces.actions.recreate')}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed' || s === 'provisioning') && (
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
            disabled={!onStart || isStarting}
          >
            {isStarting && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
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
        {s === 'running' && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2 text-xs font-semibold text-green-700 border-green-600 hover:bg-green-50"
            onClick={() => setShellOpen(true)}
            aria-label={t('workspaces.ssh.shellButton')}
          >
            {t('admin.sshTerminal.openBtn')}
          </Button>
        )}
        {s === 'running' && <InitializersMenu wsName={spec.name} enabled />}
        {s === 'running' && (
          <Button size="sm" variant="outline" onClick={() => setAddVmOpen(true)}>
            {t('workspaces.testVm.btn')}
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
      {shellOpen && (
        <WorkspaceSshTerminalWindow
          wsName={spec.name}
          shell
          onClose={() => setShellOpen(false)}
        />
      )}
      <AddTestVmDialog
        wsName={spec.name}
        open={addVmOpen}
        onClose={() => setAddVmOpen(false)}
      />
      <LogDialog
        workspaceName={spec.name}
        open={logsOpen}
        onOpenChange={setLogsOpen}
        status={status.status}
      />
      <Dialog open={recreateOpen} onOpenChange={setRecreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.confirm.recreateTitle')}</DialogTitle>
            <DialogDescription>
              {t('workspaces.confirm.recreateDescription', { name: spec.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setRecreateOpen(false)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setRecreateOpen(false)
                onRecreate?.(spec.name)
              }}
            >
              {t('workspaces.confirm.confirmRecreate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.confirm.deleteTitle')}</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2">
                <p>{t('workspaces.confirm.deleteDescription', { name: spec.name })}</p>
                <p>{t('workspaces.confirm.deleteShelveChoice')}</p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setConfirmOpen(false)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setConfirmOpen(false)
                onDelete(spec.name, true)
              }}
            >
              {t('workspaces.confirm.confirmShelve')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setConfirmOpen(false)
                onDelete(spec.name, false)
              }}
            >
              {t('workspaces.confirm.confirmForce')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
