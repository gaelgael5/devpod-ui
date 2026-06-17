import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface WorkspaceStartRecipe {
  id: string
  description: string
  type: 'start'
}

export function useWorkspaceSessions(wsName: string | undefined) {
  return useQuery({
    queryKey: ['workspace-sessions', wsName],
    queryFn: () => apiFetchJson<string[]>(`/me/workspaces/${wsName}/sessions`),
    enabled: !!wsName,
    refetchInterval: 5_000,
  })
}

export function useWorkspaceStartRecipes(wsName: string | undefined) {
  return useQuery({
    queryKey: ['workspace-start-recipes', wsName],
    queryFn: () => apiFetchJson<WorkspaceStartRecipe[]>(`/me/workspaces/${wsName}/start-recipes`),
    enabled: !!wsName,
    staleTime: 60_000,
  })
}

interface CreateInput {
  wsName: string
  name: string
  startRecipe?: string
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ wsName, name, startRecipe }: CreateInput) =>
      apiFetchJson<{ name: string }>(`/me/workspaces/${wsName}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, start_recipe: startRecipe ?? null }),
      }),
    onSuccess: (_, { wsName }) => {
      qc.invalidateQueries({ queryKey: ['workspace-sessions', wsName] })
    },
  })
}
