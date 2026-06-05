import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import { isTransient } from './types'
import type { WorkspaceStatus } from './types'

export function useWorkspaceStatus(name: string) {
  return useQuery<WorkspaceStatus>({
    queryKey: ['workspace-status', name],
    queryFn: () => apiFetchJson<WorkspaceStatus>(`/me/workspaces/${name}/status`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return isTransient(status) ? 3_000 : 10_000
    },
  })
}
