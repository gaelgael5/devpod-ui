import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface LogsConfig {
  enabled: boolean
  grafana_url: string | null
}

export function useLogsConfig() {
  return useQuery<LogsConfig>({
    queryKey: ['logs-config'],
    queryFn: () => apiFetchJson<LogsConfig>('/me/logs-config'),
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * Construit un deep-link Grafana Explore pour une expression LogQL.
 * Retourne grafana_url + /explore (sans filtre) si logql est absent.
 */
export function buildGrafanaExploreUrl(
  grafanaUrl: string,
  logql?: string,
  range = 'now-1h',
): string {
  const base = grafanaUrl.replace(/\/$/, '')
  if (!logql) return `${base}/explore`
  const left = JSON.stringify({
    datasource: 'Loki',
    queries: [{ expr: logql, refId: 'A' }],
    range: { from: range, to: 'now' },
  })
  return `${base}/explore?orgId=1&left=${encodeURIComponent(left)}`
}
