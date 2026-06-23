import { useQuery, useMutation } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface WorkspaceInitializer {
  id: string
  description: string
  version: string
}

export interface RunInitializerResult {
  applied: boolean
  already_applied: boolean
  log: string
}

export function useWorkspaceInitializers(wsName: string | undefined) {
  return useQuery({
    queryKey: ['workspace-initializers', wsName],
    queryFn: () =>
      apiFetchJson<WorkspaceInitializer[]>(`/me/workspaces/${wsName}/initializers`),
    enabled: !!wsName,
    staleTime: 60_000,
  })
}

interface RunInput {
  wsName: string
  id: string
  force?: boolean
}

export function useRunInitializer() {
  return useMutation({
    mutationFn: ({ wsName, id, force }: RunInput) =>
      apiFetchJson<RunInitializerResult>(
        `/me/workspaces/${wsName}/initializers/${id}/run${force ? '?force=true' : ''}`,
        { method: 'POST' },
      ),
  })
}
