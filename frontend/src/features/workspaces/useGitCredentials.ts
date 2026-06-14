import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface GitCredential {
  name: string
  host: string
  kind: 'ssh' | 'token'
}

export function useGitCredentials() {
  return useQuery<GitCredential[]>({
    queryKey: ['git-credentials'],
    queryFn: () => apiFetchJson<GitCredential[]>('/me/git-credentials'),
    staleTime: 60 * 1000,
  })
}
