import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface HypervisorConfig {
  name: string
  address: string
  ssh_user: string
  ssh_port: number
  ssh_key_path: string
  pve_node: string
  hypervisor_type: string
  password: string
}

export function useAdminProxmox() {
  const qc = useQueryClient()

  const nodesQuery = useQuery<HypervisorConfig[]>({
    queryKey: ['admin', 'hypervisors'],
    queryFn: () => apiFetchJson<HypervisorConfig[]>('/admin/hypervisors'),
    staleTime: 2 * 60 * 1000,
  })

  const deleteNode = useMutation({
    mutationFn: (name: string) => apiFetch(`/admin/hypervisors/${name}`, { method: 'DELETE' }),
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
