import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface HypervisorAction {
  label: string
  slug: string
  /** URL du descripteur JSON, meme format que `add_script`. */
  script: string
  /**
   * Local a l'edition : le slug a ete saisi a la main, il ne suit plus le
   * libelle. Jamais envoye au backend (`extra="forbid"` le refuserait).
   */
  slugManuel?: boolean
}

export interface HypervisorTypeConfig {
  label: string
  name: string
  add_script: string
  destroy_script: string
  test_host_params?: Record<string, string>
  actions?: HypervisorAction[]
}

/** Enregistre le paramétrage host de test d'un type d'hyperviseur. */
export function useAdminHypervisorTypes() {
  const qc = useQueryClient()

  const typesQuery = useQuery<HypervisorTypeConfig[]>({
    queryKey: ['admin', 'hypervisor-types'],
    queryFn: () => apiFetchJson<HypervisorTypeConfig[]>('/admin/hypervisor-types'),
    staleTime: 2 * 60 * 1000,
  })

  const addType = useMutation({
    mutationFn: (body: HypervisorTypeConfig) =>
      apiFetchJson<HypervisorTypeConfig>('/admin/hypervisor-types', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisor-types'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const updateType = useMutation({
    mutationFn: ({ name, body }: { name: string; body: Omit<HypervisorTypeConfig, 'name'> }) =>
      apiFetchJson<HypervisorTypeConfig>(`/admin/hypervisor-types/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ...body }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisor-types'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const deleteType = useMutation({
    mutationFn: (name: string) =>
      apiFetchJson(`/admin/hypervisor-types/${name}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hypervisor-types'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  return { typesQuery, addType, updateType, deleteType }
}
