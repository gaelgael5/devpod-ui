import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { CibleAction } from './useAdminHypervisorTypes'

export interface ActionDisponible {
  slug: string
  label: string
  cible: CibleAction
}

/**
 * Actions declarees par le type d'un hyperviseur, cible `hyperviseur`.
 *
 * Le backend filtre plutot que le front : c'est lui qui refuse l'execution
 * d'une action de l'autre cible, la liste et le garde-fou doivent dire la meme
 * chose depuis la meme source.
 */
export function useHypervisorActions(nodeName: string | null) {
  return useQuery<ActionDisponible[]>({
    queryKey: ['admin', 'hypervisors', nodeName, 'actions'],
    queryFn: () => apiFetchJson<ActionDisponible[]>(`/admin/hypervisors/${nodeName}/actions`),
    enabled: nodeName != null,
    staleTime: 2 * 60 * 1000,
  })
}

/** Actions de cible `machine` applicables a un noeud. Liste vide si le noeud
 *  n'a pas d'hyperviseur (enrole a la main) : la ligne n'aura pas de menu. */
export function useHostActions(hostName: string | null) {
  return useQuery<ActionDisponible[]>({
    queryKey: ['admin', 'hosts', hostName, 'actions'],
    queryFn: () => apiFetchJson<ActionDisponible[]>(`/admin/hosts/${hostName}/actions`),
    enabled: hostName != null,
    staleTime: 2 * 60 * 1000,
  })
}
