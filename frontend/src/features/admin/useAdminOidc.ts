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

export interface GrafanaOidcConfig {
  client_id: string
  has_secret: boolean
  auth_url: string | null
  token_url: string | null
  userinfo_url: string | null
  redirect_uri: string | null
  grafana_url: string | null
}

export interface GrafanaOidcUpdate {
  client_id: string
  client_secret?: string
}

export function useGrafanaOidc() {
  return useQuery<GrafanaOidcConfig>({
    queryKey: ['admin', 'grafana-oidc'],
    queryFn: () => apiFetchJson<GrafanaOidcConfig>('/admin/grafana-oidc'),
    staleTime: 60_000,
  })
}

export function useSaveGrafanaOidc() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GrafanaOidcUpdate) =>
      apiFetchJson<GrafanaOidcConfig>('/admin/grafana-oidc', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'grafana-oidc'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
