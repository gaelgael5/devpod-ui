import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface SshKeyResponse {
  public_key: string
}

export function useWorkspaceSshKey(name: string, enabled: boolean) {
  return useQuery<SshKeyResponse>({
    queryKey: ['workspace-ssh-key', name],
    queryFn: () => apiFetchJson<SshKeyResponse>(`/me/workspaces/${name}/ssh-key`),
    enabled,
    retry: false,
  })
}
