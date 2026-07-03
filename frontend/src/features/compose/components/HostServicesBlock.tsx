import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PlayCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import DeploymentRow from './DeploymentRow'
import ServiceLaunchDialog from './ServiceLaunchDialog'
import type { ComposeDeployment } from '../api/types'

interface Props {
  nodeId: string
  nodeLabel: string
  namingHint?: string
  deployments: ComposeDeployment[]
}

/**
 * Liste des déploiements compose d'un host + bouton de lancement — partagé entre
 * la vue workspace (machines de test) et la vue admin (hosts ressources).
 */
export default function HostServicesBlock({ nodeId, nodeLabel, namingHint, deployments }: Props) {
  const { t } = useTranslation()
  const [launchOpen, setLaunchOpen] = useState(false)

  return (
    <div className="flex flex-col gap-1.5">
      {deployments.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {deployments.map((dep) => (
            <DeploymentRow key={dep.uid} dep={dep} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t('compose.empty.deployments')}</p>
      )}

      <Button
        size="sm"
        variant="outline"
        className="self-start gap-1.5"
        onClick={() => setLaunchOpen(true)}
      >
        <PlayCircle className="h-3.5 w-3.5" />
        {t('workspaces.testHosts.launchService')}
      </Button>

      {launchOpen && (
        <ServiceLaunchDialog
          open
          onOpenChange={(o) => { if (!o) setLaunchOpen(false) }}
          nodeId={nodeId}
          nodeLabel={nodeLabel}
          namingHint={namingHint}
        />
      )}
    </div>
  )
}
