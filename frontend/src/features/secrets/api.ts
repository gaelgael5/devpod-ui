import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type SecretType = 'PAT_GITHUB' | 'PAT_GITLAB' | 'PAT_AZURE' | 'API_KEY'

export interface Secret {
  slug: string
  label: string
  description: string
  secret_type: SecretType | string // extensible
  secret_value_vault_ref: string | null
  storage_type: 'local' | 'harpocrate'
  vault_identifier: string | null
  owner_login: string
  is_public: boolean
  is_own: boolean
  created_at: string
}

export interface RegisterSecretBody {
  slug: string
  label: string
  description?: string
  secret_type: string
  secret_value: string
  storage_type: 'local' | 'harpocrate'
  vault_identifier?: string | null
}

export interface EditSecretBody {
  label: string
  description?: string
  new_value?: string | null
}

const QK = {
  list: () => ['secrets'] as const,
  byType: (type: string) => ['secrets', type] as const,
}

export function useSecrets(secretType?: string) {
  return useQuery({
    queryKey: secretType ? QK.byType(secretType) : QK.list(),
    queryFn: () => {
      const url = secretType
        ? `/me/secrets?type=${encodeURIComponent(secretType)}`
        : '/me/secrets'
      return apiFetchJson<Secret[]>(url)
    },
  })
}

export function useRegisterSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RegisterSecretBody) =>
      apiFetchJson<{ slug: string }>('/me/secrets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useEditSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: EditSecretBody & { slug: string }) =>
      apiFetchJson<{ slug: string }>(
        `/me/secrets/${encodeURIComponent(slug)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useRevealSecret() {
  // Mutation, pas query — pour éviter le cache de la valeur secrète
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchJson<{ secret_value: string }>(
        `/me/secrets/${encodeURIComponent(slug)}/value`,
      ),
  })
}

export function useDeleteSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetch(`/me/secrets/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useSetSecretVisibility() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      owner_login,
      slug,
      is_public,
    }: {
      owner_login: string
      slug: string
      is_public: boolean
    }) =>
      apiFetchJson<{ owner_login: string; slug: string; is_public: boolean }>(
        `/admin/secrets/${encodeURIComponent(owner_login)}/${encodeURIComponent(slug)}/visibility`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_public }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
