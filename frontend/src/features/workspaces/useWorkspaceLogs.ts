import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/shared/api/client'
import { isTransient } from './types'
import type { WorkspaceStatusValue } from './types'

export function useWorkspaceLogs(name: string, enabled: boolean, status?: WorkspaceStatusValue) {
  const shouldPoll = enabled && isTransient(status)
  return useQuery<string>({
    queryKey: ['workspace-logs', name],
    queryFn: async () => {
      const resp = await apiFetch(`/me/workspaces/${name}/logs`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return resp.text()
    },
    enabled,
    staleTime: 0,
    refetchInterval: shouldPoll ? 3000 : false,
  })
}
