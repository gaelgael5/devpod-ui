import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetch } from '@/shared/api/client'

export interface GitCredentialSummary {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username: string
}

interface AddCredentialPayload {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username?: string
  token?: string
  private_key?: string
}

export interface UpdateCredentialPayload {
  new_name?: string
  host?: string
  kind?: 'ssh' | 'token'
  username?: string
  token?: string         // "__UNCHANGED__" pour conserver l'existant
  private_key?: string   // "__UNCHANGED__" pour conserver l'existant
}

const QK = ['git-credentials'] as const

export function useGitCredentials() {
  return useQuery<GitCredentialSummary[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<GitCredentialSummary[]>('/me/git-credentials'),
  })
}

export function useAddGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AddCredentialPayload) =>
      apiFetchJson<GitCredentialSummary>('/me/git-credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}

export function useUpdateGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: UpdateCredentialPayload }) =>
      apiFetchJson<GitCredentialSummary>(
        `/me/git-credentials/${encodeURIComponent(name)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}

export function useDeleteGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/me/git-credentials/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}
