import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

/** Un utilisateur du portail (page Utilisateurs admin, spec 18 T4). */
export interface AdminUser {
  login: string
  email: string
  display_name: string
  termix_instance_id: string | null
}

/** Un host SSH publié, sélectionnable pour le partage (spec 18 T3). */
export interface SshHost {
  ws_id: string
  login: string
  host_name: string | null
  ssh_port: number | null
}

const USERS_QK = ['admin', 'users'] as const

export function useAdminUsers() {
  const qc = useQueryClient()

  const listQuery = useQuery<AdminUser[]>({
    queryKey: USERS_QK,
    queryFn: () => apiFetchJson<AdminUser[]>('/admin/users'),
    staleTime: 60_000,
  })

  const setInstance = useMutation({
    mutationFn: ({ login, instanceId }: { login: string; instanceId: string | null }) =>
      apiFetchJson<{ instance_id: string | null }>(
        `/admin/users/${encodeURIComponent(login)}/termix-instance`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instance_id: instanceId }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_QK }),
    onError: (e: Error) => toast.error(e.message),
  })

  return { listQuery, setInstance }
}

/** Univers des hosts SSH publiés (pour le sélecteur de partage). */
export function useSshHosts() {
  return useQuery<SshHost[]>({
    queryKey: ['admin', 'ssh-hosts'],
    queryFn: () => apiFetchJson<SshHost[]>('/admin/ssh-hosts'),
    staleTime: 60_000,
  })
}

/** Hosts accordés à un user (T3). `enabled` pour ne charger qu'à l'ouverture du dialogue. */
export function useHostGrants(login: string | null) {
  return useQuery<{ hosts: string[] }>({
    queryKey: ['admin', 'host-grants', login],
    queryFn: () =>
      apiFetchJson<{ hosts: string[] }>(
        `/admin/users/${encodeURIComponent(login as string)}/host-grants`,
      ),
    enabled: login !== null,
  })
}

export function useSetHostGrants() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ login, hosts }: { login: string; hosts: string[] }) =>
      apiFetchJson<{ hosts: string[] }>(
        `/admin/users/${encodeURIComponent(login)}/host-grants`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ hosts }),
        },
      ),
    onSuccess: (_r, v) =>
      qc.invalidateQueries({ queryKey: ['admin', 'host-grants', v.login] }),
    onError: (e: Error) => toast.error(e.message),
  })
}
