import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

interface GitBranchesResult {
  branches: string[]
  default: string | null
}

export function useGitBranches(url: string, credential = '') {
  const normalized = url.trim().replace(/\.git$/, '')
  return useQuery<GitBranchesResult>({
    queryKey: ['git', 'branches', normalized, credential],
    queryFn: () => {
      const params = new URLSearchParams({ url: normalized })
      if (credential) params.set('credential', credential)
      return apiFetchJson<GitBranchesResult>(`/me/git/branches?${params}`)
    },
    enabled: normalized.length > 5,
    staleTime: 60 * 1000,
    retry: false,
  })
}
