import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface AgentMessage {
  id: string
  created_at: string
  from_ws_id: string
  to_ws_id: string
  from_name: string
  to_name: string
  from_session: string | null
  subject: string
  body: string
  reply_to: string | null
  status: 'pending' | 'delivered' | 'cancelled'
  delivered_at: string | null
  delivered_to_session: string | null
}

export interface AgentMessageReply {
  message_id: string
  status: string
  created_at: string | null
}

export interface AgentMessageDetail extends AgentMessage {
  replies: AgentMessageReply[]
}

/** File de délivrance : messages inter-agents en attente de l'utilisateur. */
export function usePendingAgentMessages() {
  return useQuery<AgentMessage[]>({
    queryKey: ['agent-messages', 'pending'],
    queryFn: () => apiFetchJson<AgentMessage[]>('/me/agent-messages?status=pending'),
    refetchInterval: 10_000,
  })
}

/** Compteur de pending entrants par nom de workspace (badge des cartes). */
export function usePendingCounts() {
  return useQuery<Record<string, number>>({
    queryKey: ['agent-messages', 'pending-counts'],
    queryFn: () => apiFetchJson<Record<string, number>>('/me/agent-messages/pending-counts'),
    refetchInterval: 10_000,
  })
}

export function useAgentMessageDetail(id: string | null) {
  return useQuery<AgentMessageDetail>({
    queryKey: ['agent-messages', 'detail', id],
    queryFn: () => apiFetchJson<AgentMessageDetail>(`/me/agent-messages/${encodeURIComponent(id!)}`),
    enabled: !!id,
  })
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['agent-messages'] })
}

export function useDeliverAgentMessage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, session }: { id: string; session: string }) => {
      const res = await apiFetch(`/me/agent-messages/${encodeURIComponent(id)}/deliver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail || `HTTP ${res.status}`)
      }
      return res.json()
    },
    onSuccess: () => invalidate(qc),
  })
}

export function useCancelAgentMessage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await apiFetch(`/me/agent-messages/${encodeURIComponent(id)}/cancel`, {
        method: 'POST',
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail || `HTTP ${res.status}`)
      }
    },
    onSuccess: () => invalidate(qc),
  })
}
