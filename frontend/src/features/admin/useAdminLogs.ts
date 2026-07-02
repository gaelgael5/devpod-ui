import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface LogsConfig {
  enabled: boolean
  loki_push_url: string
  loki_query_url: string
  grafana_url: string
  module: string
  has_push_token: boolean
}

export interface LogsConfigUpdate {
  enabled: boolean
  loki_push_url: string
  loki_query_url: string
  grafana_url: string
  module: string
  push_token?: string
}

export function useAdminLogs() {
  return useQuery<LogsConfig>({
    queryKey: ['admin', 'logs-config'],
    queryFn: () => apiFetchJson<LogsConfig>('/admin/logs-config'),
    staleTime: 60_000,
  })
}

export function useSaveLogs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: LogsConfigUpdate) =>
      apiFetchJson<LogsConfig>('/admin/logs-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'logs-config'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
