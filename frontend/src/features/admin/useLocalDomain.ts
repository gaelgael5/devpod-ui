import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface LocalDomain {
  local_domain: string
}

export function useLocalDomain() {
  return useQuery<LocalDomain>({
    queryKey: ['admin', 'local-domain'],
    queryFn: () => apiFetchJson<LocalDomain>('/admin/local-domain'),
    staleTime: 60_000,
  })
}

export function useSaveLocalDomain() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (local_domain: string) =>
      apiFetchJson<LocalDomain>('/admin/local-domain', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ local_domain }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'local-domain'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
