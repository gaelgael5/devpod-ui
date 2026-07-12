import { useTranslation } from 'react-i18next'
import DeploymentRow from './DeploymentRow'
import ServiceLaunchDialog from './ServiceLaunchDialog'
import type { ComposeDeployment } from '../api/types'

interface Props {
  nodeId: string
  nodeLabel: string
  namingHint?: string
  deployments: ComposeDeployment[]
  /** Ouverture du dialog de lancement — pilotée par le parent (item du menu ⋮ du host). */
  launchOpen: boolean
  onLaunchOpenChange: (open: boolean) => void
}

/**
 * Liste des déploiements compose d'un host — partagé entre la vue workspace
 * (machines de test) et la vue admin (hosts ressources). Le déclencheur
 * « Démarrer un service » vit dans le menu d'actions (⋮) du host, côté parent ;
 * le dialog reste ici pour mutualiser nodeId/nodeLabel/namingHint.
 */
export default function HostServicesBlock({
  nodeId, nodeLabel, namingHint, deployments, launchOpen, onLaunchOpenChange,
}: Props) {
  const { t } = useTranslation()

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

      {launchOpen && (
        <ServiceLaunchDialog
          open
          onOpenChange={onLaunchOpenChange}
          nodeId={nodeId}
          nodeLabel={nodeLabel}
          namingHint={namingHint}
        />
      )}
    </div>
  )
}
