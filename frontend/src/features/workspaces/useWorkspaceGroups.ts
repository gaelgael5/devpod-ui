import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetchJson } from '@/shared/api/client'

export interface WorkspaceGroup {
  id: number
  name: string
  created_at: string
}

const QK = ['workspace-groups'] as const

export function useWorkspaceGroups() {
  return useQuery<WorkspaceGroup[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<WorkspaceGroup[]>('/me/workspace-groups'),
    staleTime: 30_000,
  })
}

export function useCreateGroup() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetchJson<WorkspaceGroup>('/me/workspace-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(t('groups.error.create', { message: err.message })),
  })
}

export function useRenameGroup() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      apiFetchJson<WorkspaceGroup>(`/me/workspace-groups/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK })
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => toast.error(t('groups.error.rename', { message: err.message })),
  })
}

export function useDeleteGroup() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetchJson<void>(`/me/workspace-groups/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK })
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => toast.error(t('groups.error.delete', { message: err.message })),
  })
}

export function useSetWorkspaceGroups() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: ({ workspaceName, groups }: { workspaceName: string; groups: string[] }) =>
      apiFetchJson<{ workspace: string; groups: string[] }>(
        `/me/workspaces/${encodeURIComponent(workspaceName)}/groups`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ groups }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspaces'] }),
    onError: (err: Error) => toast.error(t('groups.error.assign', { message: err.message })),
  })
}
