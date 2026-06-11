import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface HostConfig {
  name: string
  type: 'docker-tls' | 'ssh'
  default?: boolean
  docker_host?: string
  address?: string
  key_path?: string
}

export function useHosts() {
  return useQuery<HostConfig[]>({
    queryKey: ['admin', 'hosts'],
    queryFn: () => apiFetchJson<HostConfig[]>('/admin/hosts'),
    staleTime: 2 * 60 * 1000,
  })
}

export function useAddHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (host: HostConfig) =>
      apiFetchJson<HostConfig>('/admin/hosts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(host),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useUpdateHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (host: HostConfig) =>
      apiFetchJson<HostConfig>(`/admin/hosts/${encodeURIComponent(host.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(host),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useDeleteHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/admin/hosts/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useHostCert(name: string, enabled: boolean) {
  return useQuery<Record<string, string>>({
    queryKey: ['admin', 'hosts', name, 'cert'],
    queryFn: () => apiFetchJson<Record<string, string>>(`/admin/hosts/${encodeURIComponent(name)}/cert`),
    enabled,
    retry: false,
  })
}
