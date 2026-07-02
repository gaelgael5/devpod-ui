import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  MoreVertical, Play, PlayCircle, RefreshCw, RotateCw, ScrollText, Square, TerminalSquare, Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { STATUS_TONE_CLASS } from './statusTone'
import { useDeleteTestHost, useResolveTestHostIp, type TestHost } from './useTestVm'
import {
  useDeploymentAction, useDeleteDeployment, useDeploymentLogs,
} from '@/features/compose/hooks/useCompose'
import type { ComposeDeployment, DeploymentStatus } from '@/features/compose/api/types'
import ServiceLaunchDialog from '@/features/compose/components/ServiceLaunchDialog'

const COMPOSE_STATUS_CLASS: Record<DeploymentStatus, string> = {
  running: STATUS_TONE_CLASS.running,
  partial: STATUS_TONE_CLASS.progress,
  stopped: STATUS_TONE_CLASS.stopped,
  error: STATUS_TONE_CLASS.error,
  created: STATUS_TONE_CLASS.neutral,
}

function DeploymentLogsDialog({ uid, id, open, onOpenChange }: { uid: string; id: string; open: boolean; onOpenChange: (v: boolean) => void }) {
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

function ServiceRow({ dep }: { dep: ComposeDeployment }) {
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
      </div>
      <DeploymentLogsDialog uid={dep.uid} id={dep.id} open={logsOpen} onOpenChange={setLogsOpen} />
    </>
  )
}

interface Props {
  wsName: string
  host: TestHost
  deployments: ComposeDeployment[]
  onOpenSsh: (host: TestHost) => void
}

/**
 * Bloc d'une machine de test : barre d'en-tête (alias + nom/IP + menu d'actions)
 * et, en dessous, les services docker-compose qui y tournent — un seul bloc
 * visuel qui regroupe la machine et ce qui s'exécute dedans.
 */
export default function TestHostBlock({ wsName, host, deployments, onOpenSsh }: Props) {
  const { t } = useTranslation()
  const del = useDeleteTestHost(wsName)
  const resolve = useResolveTestHostIp(wsName)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [launchOpen, setLaunchOpen] = useState(false)

  function handleResolve() {
    toast.promise(resolve.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.resolving'),
      success: (r) => t('workspaces.testHosts.resolved', { ip: r.ip }),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.resolveFailed')),
    })
  }

  function confirmDeleteHost() {
    setConfirmDelete(false)
    toast.promise(del.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.deleting'),
      success: t('workspaces.testHosts.deleted'),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.deleteFailed')),
    })
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="font-semibold text-sm truncate">{host.alias}</span>
          <span className="font-mono text-xs text-muted-foreground truncate">
            {host.name} · {host.ip}
          </span>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0 shrink-0"
              aria-label={t('workspaces.testHosts.actionsMenu')}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onSelect={() => onOpenSsh(host)} className="gap-2">
              <TerminalSquare className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.openSsh')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleResolve} className="gap-2">
              <RefreshCw className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.resolveIp')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setLaunchOpen(true)} className="gap-2">
              <PlayCircle className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.launchService')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="gap-2 text-destructive focus:text-destructive"
              onSelect={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {deployments.length > 0 ? (
        <div className="flex flex-col gap-1.5 p-2">
          {deployments.map((dep) => (
            <ServiceRow key={dep.uid} dep={dep} />
          ))}
        </div>
      ) : (
        <p className="px-3 py-2 text-xs text-muted-foreground">{t('compose.empty.deployments')}</p>
      )}

      {launchOpen && (
        <ServiceLaunchDialog
          open
          onOpenChange={(o) => { if (!o) setLaunchOpen(false) }}
          nodeId={host.name}
          nodeLabel={host.alias}
        />
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.testHosts.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('workspaces.testHosts.deleteDescription', { alias: host.alias, name: host.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              {t('workspaces.testVm.cancel')}
            </Button>
            <Button variant="destructive" size="sm" onClick={confirmDeleteHost}>
              {t('workspaces.testHosts.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
