import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface RuleDeliveryDetail {
  rule: string
  rule_id?: string
  matched?: boolean
  actions_ran?: number
  chain_stopped?: string
  error?: string
}

export interface AppEventDelivery {
  id: number
  event_id: string
  listener: string
  status: 'ok' | 'error'
  error: string | null
  detail: RuleDeliveryDetail[] | null
  finished_at: string
}

export interface AppEventEntry {
  id: string
  type: string
  actor: string
  workspace: string | null
  subject: Record<string, unknown>
  correlation_id: string | null
  occurred_at: string
  deliveries: AppEventDelivery[]
}

const QK = {
  list: () => ['app-events'] as const,
}

export function useAppEvents() {
  return useQuery({
    queryKey: QK.list(),
    queryFn: () => apiFetchJson<AppEventEntry[]>('/me/events'),
  })
}

export function useReplayEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<{ replayed: string }>(`/me/events/${encodeURIComponent(id)}/replay`, {
        method: 'POST',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
