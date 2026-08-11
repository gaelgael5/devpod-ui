import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface BastionConfig {
  enabled: boolean
  api_url: string
  host: string
  port: number
  role: string
  apikey_secret: string
}

export function useAdminBastion() {
  return useQuery<BastionConfig>({
    queryKey: ['admin', 'bastion-config'],
    queryFn: () => apiFetchJson<BastionConfig>('/admin/bastion-config'),
    staleTime: 60_000,
  })
}

export function useSaveBastion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BastionConfig) =>
      apiFetchJson<BastionConfig>('/admin/bastion-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'bastion-config'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
