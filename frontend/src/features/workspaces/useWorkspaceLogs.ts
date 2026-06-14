import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/shared/api/client'

export function useWorkspaceLogs(name: string, enabled: boolean) {
  return useQuery<string>({
    queryKey: ['workspace-logs', name],
    queryFn: async () => {
      const resp = await apiFetch(`/me/workspaces/${name}/logs`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return resp.text()
    },
    enabled,
    staleTime: 0,
    refetchInterval: enabled ? 3000 : false,
  })
}
