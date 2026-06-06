import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface HostConfig {
  name: string
  type: string
  default?: boolean
  docker_host?: string
}

export function useHosts() {
  return useQuery<HostConfig[]>({
    queryKey: ['admin', 'hosts'],
    queryFn: () => apiFetchJson<HostConfig[]>('/admin/hosts'),
    staleTime: 2 * 60 * 1000,
  })
}
