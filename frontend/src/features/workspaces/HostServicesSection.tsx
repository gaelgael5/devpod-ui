import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ScrollText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useTestHosts } from './useTestVm'
import { useDeployments, useDeploymentAction, useDeleteDeployment, useDeploymentLogs } from '@/features/compose/hooks/useCompose'
import type { ComposeDeployment, DeploymentStatus } from '@/features/compose/api/types'

function statusVariant(s: DeploymentStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (s === 'running') return 'default'
  if (s === 'partial') return 'secondary'
  if (s === 'error') return 'destructive'
  return 'outline'
}

function DeploymentLogsDialog({ id, open, onOpenChange }: { id: string; open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useTranslation()
  const { data, isLoading } = useDeploymentLogs(id, open)

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
        <Badge variant={statusVariant(dep.status)} className="text-xs shrink-0">
          {t(`compose.status.${dep.status}`)}
        </Badge>
        {dep.host_ports.length > 0 && (
          <span className="text-xs text-muted-foreground shrink-0">
            :{dep.host_ports.join(', :')}
          </span>
        )}
        <div className="flex gap-1 shrink-0">
          {dep.status === 'stopped' && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              disabled={pending}
              onClick={() => action.mutate({ id: dep.id, action: 'start' })}
            >
              {t('compose.actions.start')}
            </Button>
          )}
          {dep.status !== 'stopped' && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              disabled={pending}
              onClick={() => action.mutate({ id: dep.id, action: 'stop' })}
            >
              {t('compose.actions.stop')}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            disabled={pending}
            onClick={() => action.mutate({ id: dep.id, action: 'restart' })}
          >
            {t('compose.actions.restart')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={() => setLogsOpen(true)}
            aria-label={t('compose.logs.button')}
          >
            <ScrollText className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs text-destructive hover:text-destructive"
            disabled={pending}
            onClick={() => del.mutate(dep.id)}
          >
            {t('compose.actions.down')}
          </Button>
        </div>
      </div>
      <DeploymentLogsDialog id={dep.id} open={logsOpen} onOpenChange={setLogsOpen} />
    </>
  )
}

interface Props {
  wsName: string
  enabled: boolean
}

/**
 * Affiche les services docker-compose actifs sur les machines de test du workspace.
 * Chaque service a des boutons stop/restart/down inline.
 */
export default function HostServicesSection({ wsName, enabled }: Props) {
  const { data: hosts = [] } = useTestHosts(wsName, enabled)
  const { data: allDeployments = [] } = useDeployments()

  if (hosts.length === 0) return null

  const hostNames = new Set(hosts.map((h) => h.name))
  const deployments = allDeployments.filter((d) => hostNames.has(d.node_id))

  if (deployments.length === 0) return null

  return (
    <div className="mt-3 flex flex-col gap-1.5">
      {deployments.map((dep) => (
        <ServiceRow key={dep.id} dep={dep} />
      ))}
    </div>
  )
}
