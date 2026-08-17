import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type SessionFamily = 'workspace' | 'host' | 'test'

export interface SessionEntry {
  family: SessionFamily
  target: string
  owner: string
  session: string | null
  attached: boolean
  unreachable?: boolean
  workspace?: string
  /** Nœud sur lequel la session tourne (conteneur → nœud devpod ; host/test → lui-même). */
  host?: string | null
  /** Session vivante alors que le workspace n'est PAS suivi « running » (oubliée du registre). */
  orphan?: boolean
  /** tmux absent sur ce host : terminal en shell simple, session NON persistante. */
  no_tmux?: boolean
  /** Occupation disque de la machine (hosts, ressources, VM de test).
   *  Absent = jamais sondé — on n'affiche alors RIEN plutôt qu'un faux « 0 % ».
   *  Alimenté par la sonde horaire du portail, pas par une mesure à la volée. */
  disk?: DiskUsage
  /** Mémoire de la machine. « Utilisé » exclut le cache récupérable. */
  memory?: MemoryUsage
  /** Charge CPU ramenée au nombre de cœurs : 100 % = tous les cœurs saturés. */
  cpu?: CpuUsage
  /** Sonde tmux non aboutie dans le délai de première peinture : l'UI affiche
   *  « … » plutôt que d'affirmer à tort qu'il n'y a aucune session. */
  pending?: boolean
}

export interface MemoryUsage {
  total_bytes: number | null
  used_bytes: number | null
  used_pct: number
}

export interface CpuUsage {
  used_pct: number
  cores: number | null
}

export interface DiskUsage {
  total_bytes: number | null
  used_bytes: number | null
  avail_bytes: number | null
  used_pct: number
  /** Au-dessus du seuil configuré (90 % par défaut) — décidé par le serveur. */
  warn: boolean
  measured_at: string | null
  /** Dernière sonde en échec : la valeur affichée est la précédente. */
  stale_error?: string | null
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

export interface CloseSessionInput {
  family: SessionFamily
  target: string
  owner: string
  session: string | null
}

/** Fermeture centralisée d'une session (toutes familles).

 Détache le pont vivant ; pour un workspace, tue en plus la session tmux. Un
 admin peut fermer la session d'un autre user (le backend applique le contrôle). */
export function useCloseSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: CloseSessionInput) => {
      const res = await apiFetch('/sessions/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || res.statusText)
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}
