import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/shared/api/client'

export interface WorkspaceMessage {
  id: number | null
  type: string
  message: string
  created_at: string | null
}

export function useWorkspaceMessages(name: string, enabled: boolean) {
  return useQuery<WorkspaceMessage[]>({
    queryKey: ['workspace-messages', name],
    queryFn: async () => {
      const resp = await apiFetch(`/me/workspaces/${name}/messages`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return resp.json() as Promise<WorkspaceMessage[]>
    },
    enabled,
    staleTime: 30_000,
  })
}
