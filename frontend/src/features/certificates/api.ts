import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type CertType =
  | 'ssh-ed25519' | 'ssh-rsa-2048' | 'ssh-rsa-4096' | 'ssh-ecdsa-p256'
  | 'tls-rsa-2048' | 'tls-rsa-4096' | 'tls-ec-p256' | 'tls-ec-p384'

export interface Certificate {
  slug: string
  label: string
  description: string
  cert_type: CertType
  public_key: string
  storage_type: 'local' | 'harpocrate'
  vault_identifier: string | null
  owner_login: string
  is_public: boolean
  is_own: boolean
  created_at: string
}

export interface GenerateBody {
  slug: string
  label: string
  description?: string
  cert_type: CertType
  storage_type: 'local' | 'harpocrate'
  vault_identifier?: string | null
}

export interface RegisterBody extends GenerateBody {
  public_key: string
  private_key_pem: string
}

const QK = {
  list: () => ['certificates'] as const,
}

export function useCertificates() {
  return useQuery({
    queryKey: QK.list(),
    queryFn: () => apiFetchJson<Certificate[]>('/me/certificates'),
  })
}

export function useGenerateCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GenerateBody) =>
      apiFetchJson<{ public_key: string; slug: string }>('/me/certificates/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useRegisterCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RegisterBody) =>
      apiFetchJson<{ slug: string }>('/me/certificates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useDeleteCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetch(`/me/certificates/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useRevealPrivateKey() {
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchJson<{ private_key_pem: string }>(
        `/me/certificates/${encodeURIComponent(slug)}/private`,
      ),
  })
}

export interface EditCertBody {
  label: string
  description?: string
  new_public_key?: string | null
  new_private_key_pem?: string | null
}

export function useUpdateCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: EditCertBody & { slug: string }) =>
      apiFetchJson<{ slug: string }>(
        `/me/certificates/${encodeURIComponent(slug)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useSetCertVisibility() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ owner_login, slug, is_public }: { owner_login: string; slug: string; is_public: boolean }) =>
      apiFetchJson<{ owner_login: string; slug: string; is_public: boolean }>(
        `/admin/certificates/${encodeURIComponent(owner_login)}/${encodeURIComponent(slug)}/visibility`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_public }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
