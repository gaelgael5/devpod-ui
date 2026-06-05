import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useWorkspaces } from './useWorkspaces'
import { useWorkspaceStatus } from './useWorkspaceStatus'
import { useWorkspaceOps } from './useWorkspaceOps'
import WorkspaceCard from './WorkspaceCard'
import type { WorkspaceSpec } from './types'

function WorkspaceRow(spec: WorkspaceSpec) {
  const { data: status } = useWorkspaceStatus(spec.name)
  const { stopWorkspace, deleteWorkspace, createWorkspace } = useWorkspaceOps()

  const liveStatus = status ?? { ws_id: `?-${spec.name}`, status: 'unknown' as const }

  return (
    <WorkspaceCard
      spec={spec}
      status={liveStatus}
      onStop={(n) => stopWorkspace.mutate(n)}
      onDelete={(n) => deleteWorkspace.mutate(n)}
      onStart={(n) =>
        createWorkspace.mutate({ name: n, source: spec.source, host: spec.host, recipes: spec.recipes })
      }
    />
  )
}

export default function WorkspaceList() {
  const { t } = useTranslation()
  const { data: workspaces, isLoading } = useWorkspaces()

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('workspaces.title')}</h1>
        <Button asChild>
          <Link to="/workspaces/new">{t('workspaces.new')}</Link>
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}

      {!isLoading && !workspaces?.length && (
        <p className="text-muted-foreground">{t('workspaces.empty')}</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {workspaces?.map((ws) => (
          <WorkspaceRow key={ws.name} {...ws} />
        ))}
      </div>
    </div>
  )
}
