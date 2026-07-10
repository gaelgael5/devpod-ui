import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export type SessionFamily = 'workspace' | 'host' | 'test'

export interface SessionEntry {
  family: SessionFamily
  target: string
  owner: string
  session: string | null
  attached: boolean
  unreachable?: boolean
  workspace?: string
}

/** Vue centralisée des sessions actives (conteneurs, hosts, VM de test).

 User → ses propres sessions ; admin → tout. Rafraîchi régulièrement pour refléter
 les rattachements (badge « attaché »). */
export function useSessions() {
  return useQuery<SessionEntry[]>({
    queryKey: ['sessions'],
    queryFn: () => apiFetchJson<SessionEntry[]>('/sessions'),
    refetchInterval: 8_000,
  })
}
