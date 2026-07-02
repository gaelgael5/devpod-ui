import TestHostBlock from './TestHostBlock'
import { useTestHosts, type TestHost } from './useTestVm'
import { useDeployments } from '@/features/compose/hooks/useCompose'

interface Props {
  wsName: string
  enabled: boolean
  onOpenSsh: (host: TestHost) => void
}

/**
 * Un bloc par machine de test attachée au workspace : alias/nom/IP + menu
 * d'actions en en-tête, services docker-compose qui y tournent en dessous.
 */
export default function HostServicesSection({ wsName, enabled, onOpenSsh }: Props) {
  const { data: hosts = [] } = useTestHosts(wsName, enabled)
  const { data: allDeployments = [] } = useDeployments()

  if (hosts.length === 0) return null

  return (
    <div className="mt-3 flex flex-col gap-3">
      {hosts.map((host) => (
        <TestHostBlock
          key={host.name}
          wsName={wsName}
          host={host}
          deployments={allDeployments.filter((d) => d.node_id === host.name)}
          onOpenSsh={onOpenSsh}
        />
      ))}
    </div>
  )
}
