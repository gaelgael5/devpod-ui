import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface ProxmoxNodeConfig {
  name: string
  address: string
  ssh_user: string
  ssh_port: number
  ssh_key_path: string
  pve_node: string
  script_url: string
}

export function useAdminProxmox() {
  const qc = useQueryClient()

  const nodesQuery = useQuery<ProxmoxNodeConfig[]>({
    queryKey: ['admin', 'proxmox'],
    queryFn: () => apiFetchJson<ProxmoxNodeConfig[]>('/admin/proxmox'),
    staleTime: 2 * 60 * 1000,
  })

  const deleteNode = useMutation({
    mutationFn: (name: string) => apiFetch(`/admin/proxmox/${name}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'proxmox'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const addNode = useMutation({
    mutationFn: (fd: FormData) =>
      apiFetchJson<ProxmoxNodeConfig>('/admin/proxmox', { method: 'POST', body: fd }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'proxmox'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const updateNode = useMutation({
    mutationFn: ({ name, fd }: { name: string; fd: FormData }) =>
      apiFetchJson<ProxmoxNodeConfig>(`/admin/proxmox/${name}`, { method: 'PUT', body: fd }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'proxmox'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  return { nodesQuery, deleteNode, addNode, updateNode }
}
