import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface GitCredentialSummary {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username: string
}

export interface AddCredentialPayload {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username?: string
  cert_slug?: string    // si kind=ssh
  secret_slug?: string  // si kind=token
}

export interface UpdateCredentialPayload {
  new_name?: string
  host?: string
  kind?: 'ssh' | 'token'
  username?: string
  cert_slug?: string | null    // si kind=ssh
  secret_slug?: string | null  // si kind=token
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

export interface TestCredentialResult {
  ok: boolean
  message: string
}

export function useTestGitCredential() {
  return useMutation({
    mutationFn: (name: string) =>
      apiFetchJson<TestCredentialResult>(
        `/me/git-credentials/${encodeURIComponent(name)}/test`,
        { method: 'POST' },
      ),
  })
}
