import { useQuery } from '@tanstack/react-query'
import type { Query } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import { isTransient } from './types'
import type { WorkspaceStatus } from './types'

/** Options partagées entre useWorkspaceStatus (carte) et useQueries (tri des groupes). */
export function workspaceStatusQueryOptions(name: string) {
  return {
    queryKey: ['workspace-status', name] as const,
    queryFn: () => apiFetchJson<WorkspaceStatus>(`/me/workspaces/${name}/status`),
    refetchInterval: (query: Query<WorkspaceStatus>) => {
      const status = query.state.data?.status
      return isTransient(status) ? 3_000 : 10_000
    },
  }
}

export function useWorkspaceStatus(name: string) {
  return useQuery<WorkspaceStatus>(workspaceStatusQueryOptions(name))
}
