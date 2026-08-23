import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetch } from '@/shared/api/client'

export interface WorkspaceStartRecipe {
  id: string
  description: string
  type: 'start'
}

export function useWorkspaceSessions(wsName: string | undefined) {
  return useQuery({
    queryKey: ['workspace-sessions', wsName],
    queryFn: () =>
      apiFetchJson<string[]>(`/me/workspaces/${encodeURIComponent(wsName ?? '')}/sessions`),
    enabled: !!wsName,
    refetchInterval: 5_000,
  })
}

/**
 * Combien de terminaux du portail regardent cette session tmux.
 *
 * Deux appareils sur la meme session, c'est tmux qui cale la fenetre sur le
 * client le plus recemment actif : l'ecran le plus petit recoit des lignes trop
 * longues et se retrouve deforme, sans que rien ne l'explique.
 */
export function useSessionClients(wsName: string | undefined, session: string | null) {
  return useQuery({
    queryKey: ['session-clients', wsName, session],
    queryFn: () =>
      apiFetchJson<{ clients: number }>(
        `/me/workspaces/${encodeURIComponent(wsName ?? '')}/sessions/` +
          `${encodeURIComponent(session ?? '')}/clients`,
      ),
    enabled: !!wsName && !!session,
    // Plus lache que la liste des sessions : c'est un avertissement, pas un etat
    // dont depend l'affichage.
    refetchInterval: 15_000,
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
      apiFetchJson<{ name: string }>(
        `/me/workspaces/${encodeURIComponent(wsName)}/sessions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, start_recipe: startRecipe ?? null }),
        },
      ),
    onSuccess: (_, { wsName }) => {
      qc.invalidateQueries({ queryKey: ['workspace-sessions', wsName] })
    },
  })
}

interface DeleteInput {
  wsName: string
  sessionName: string
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ wsName, sessionName }: DeleteInput) => {
      const res = await apiFetch(
        `/me/workspaces/${encodeURIComponent(wsName)}/sessions/${encodeURIComponent(sessionName)}`,
        { method: 'DELETE' },
      )
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || res.statusText)
      }
    },
    onSuccess: (_, { wsName }) => {
      qc.invalidateQueries({ queryKey: ['workspace-sessions', wsName] })
    },
  })
}
