import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { WorkspaceSpec } from './types'

export function useWorkspaces() {
  return useQuery<WorkspaceSpec[]>({
    queryKey: ['workspaces'],
    queryFn: () => apiFetchJson<WorkspaceSpec[]>('/me/workspaces'),
    staleTime: 30_000,
  })
}
