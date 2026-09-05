import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export interface HypervisorConfig {
  name: string
  address: string
  ssh_user: string
  ssh_port: number
  ssh_key_path: string
  pve_node: string
  hypervisor_type: string
}

export interface ChargesHyperviseur {
  workspaces: number
  tests: number
  ressources: number
  /** `portail` + `autres`, agrégés — une machine portée reste une machine portée. */
  autres: number
  /** Jamais sondées : ni actives ni arrêtées — leur cas doit se voir. */
  jamais_sondees: number
}

export interface ChargesMachines {
  par_hyperviseur: Record<string, ChargesHyperviseur>
  /** Machines sans provenance : personne ne se les attribue. */
  sans_provenance: number
}

/**
 * Machines portées par hyperviseur — le contrôle visuel de l'équilibrage.
 * UNE requête agrégée pour toute la page, jamais une par ligne.
 */
export function useHypervisorCharges() {
  return useQuery<ChargesMachines>({
    queryKey: ['admin', 'hypervisors', 'charges'],
    queryFn: () => apiFetchJson<ChargesMachines>('/admin/hypervisors/charges'),
    staleTime: 60 * 1000,
  })
}

export function useAdminProxmox() {
  const qc = useQueryClient()

  const nodesQuery = useQuery<HypervisorConfig[]>({
    queryKey: ['admin', 'hypervisors'],
    queryFn: () => apiFetchJson<HypervisorConfig[]>('/admin/hypervisors'),
    staleTime: 2 * 60 * 1000,
  })

  const deleteNode = useMutation({
    mutationFn: (name: string) => apiFetchVoid(`/admin/hypervisors/${name}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisors'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const addNode = useMutation({
    mutationFn: (fd: FormData) =>
      apiFetchJson<HypervisorConfig>('/admin/hypervisors', { method: 'POST', body: fd }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisors'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const updateNode = useMutation({
    mutationFn: ({ name, fd }: { name: string; fd: FormData }) =>
      apiFetchJson<HypervisorConfig>(`/admin/hypervisors/${name}`, { method: 'PUT', body: fd }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisors'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  return { nodesQuery, deleteNode, addNode, updateNode }
}
