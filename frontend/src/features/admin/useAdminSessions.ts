import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

/** Durées de session, en SECONDES (contrat backend). */
export interface SessionDurations {
  session_max_age: number
  session_absolute_max_age: number
}

export function useAdminSessions() {
  return useQuery<SessionDurations>({
    queryKey: ['admin', 'sessions-config'],
    queryFn: () => apiFetchJson<SessionDurations>('/admin/sessions'),
    staleTime: 60_000,
  })
}

export function useSaveSessions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SessionDurations) =>
      apiFetchJson<SessionDurations>('/admin/sessions', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'sessions-config'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

// Défauts workspaces (enabler 59864c37) : limite mémoire par défaut des conteneurs.
export interface WorkspaceDefaults {
  memory_limit: string
}

export function useWorkspaceDefaults() {
  return useQuery<WorkspaceDefaults>({
    queryKey: ['admin', 'workspace-defaults'],
    queryFn: () => apiFetchJson<WorkspaceDefaults>('/admin/workspace-defaults'),
    staleTime: 60_000,
  })
}

export function useSaveWorkspaceDefaults() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: WorkspaceDefaults) =>
      apiFetchJson<WorkspaceDefaults>('/admin/workspace-defaults', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'workspace-defaults'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
