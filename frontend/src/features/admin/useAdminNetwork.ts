import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface NetworkConfig {
  base_domain: string
  external_url: string
  workspace_host: string
}

export function useAdminNetwork() {
  return useQuery<NetworkConfig>({
    queryKey: ['admin', 'network'],
    queryFn: () => apiFetchJson<NetworkConfig>('/admin/network'),
    staleTime: 60_000,
  })
}

export function useSaveNetwork() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: NetworkConfig) =>
      apiFetchJson<NetworkConfig>('/admin/network', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'network'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
