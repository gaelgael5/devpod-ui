import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface OidcConfig {
  issuer: string
  client_id: string
  has_secret: boolean
  redirect_uri: string
  allow_local_auth: boolean
}

export interface OidcUpdate {
  issuer: string
  client_id: string
  client_secret?: string
  allow_local_auth: boolean
}

export function useAdminOidc() {
  return useQuery<OidcConfig>({
    queryKey: ['admin', 'oidc'],
    queryFn: () => apiFetchJson<OidcConfig>('/admin/oidc'),
    staleTime: 60_000,
  })
}

export function useSaveOidc() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: OidcUpdate) =>
      apiFetchJson<OidcConfig>('/admin/oidc', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'oidc'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
