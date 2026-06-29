import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useTestHosts } from './useTestVm'
import { useDeployments, useDeploymentAction, useDeleteDeployment } from '@/features/compose/hooks/useCompose'
import type { ComposeDeployment, DeploymentStatus } from '@/features/compose/api/types'

function statusVariant(s: DeploymentStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (s === 'running') return 'default'
  if (s === 'partial') return 'secondary'
  if (s === 'error') return 'destructive'
  return 'outline'
}

function ServiceRow({ dep }: { dep: ComposeDeployment }) {
  const { t } = useTranslation()
  const action = useDeploymentAction()
  const del = useDeleteDeployment()
  const pending = action.isPending || del.isPending

  return (
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
          className="h-6 px-2 text-xs text-destructive hover:text-destructive"
          disabled={pending}
          onClick={() => del.mutate(dep.id)}
        >
          {t('compose.actions.down')}
        </Button>
      </div>
    </div>
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
