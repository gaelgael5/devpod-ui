import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type Transport = 'streamable_http' | 'sse' | 'stdio'
export type StorageType = 'local' | 'harpocrate'
export type ExposeMode = 'all' | 'allowlist' | 'denylist'

export type BackendHealth = 'up' | 'down' | 'unknown'

export interface MCPBackend {
  id: string
  owner_login: string
  namespace: string
  name: string
  url: string
  transport: Transport
  enabled: boolean
  created_at: string
  updated_at: string
  // Statut de santé renvoyé par le monitor (absent des réponses sans monitoring).
  health?: BackendHealth
}

export interface MCPBackendKey {
  id: string
  backend_id: string
  slug: string
  description: string
  storage_type: StorageType
  secret_value_vault_ref: string | null
  vault_identifier: string | null
  enabled: boolean
  created_at: string
}

export interface MCPApikey {
  id: string
  owner_login: string
  label: string
  revoked: boolean
  created_at: string
}

export interface MCPGrant {
  apikey_id: string
  backend_id: string
  // null = backend public (sans clé de service) — la colonne DB est nullable.
  backend_key_id: string | null
  expose_mode: ExposeMode
  expose: string[]
}

export interface BackendCreateBody {
  namespace: string
  name: string
  url: string
  transport: Transport
}

export interface BackendUpdateBody {
  name: string
  url: string
  transport: Transport
  enabled: boolean
}

export interface KeyCreateBody {
  slug: string
  description?: string
  storage_type: StorageType
  secret_value: string
  vault_identifier?: string | null
}

export interface GrantSetBody {
  backend_id: string
  // null = backend public (sans authentification) : aucune clé de service
  backend_key_id: string | null
  expose_mode: ExposeMode
  expose: string[]
}

export interface CreatedApikey {
  id: string
  token: string
}

const QK = {
  backends: () => ['mcp', 'backends'] as const,
  keys: (backendId: string | null) => ['mcp', 'keys', backendId] as const,
  apikeys: () => ['mcp', 'apikeys'] as const,
  grants: (apikeyId: string | null) => ['mcp', 'grants', apikeyId] as const,
}

// ── Backends ──────────────────────────────────────────────────────────────────

export function useBackends() {
  return useQuery({
    queryKey: QK.backends(),
    queryFn: () => apiFetchJson<MCPBackend[]>('/me/mcp/backends'),
    // Polling court : reflète le statut de santé du monitor (pas de push serveur en SDK 1.28).
    refetchInterval: 10_000,
  })
}

export function useCreateBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BackendCreateBody) =>
      apiFetchJson<{ id: string }>('/me/mcp/backends', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

export function useUpdateBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: BackendUpdateBody & { id: string }) =>
      apiFetchJson<{ id: string }>(`/me/mcp/backends/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

export function useDeleteBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/me/mcp/backends/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

// ── Clés de service ─────────────────────────────────────────────────────────────

export function useBackendKeys(backendId: string | null) {
  return useQuery({
    queryKey: QK.keys(backendId),
    queryFn: () =>
      apiFetchJson<MCPBackendKey[]>(`/me/mcp/backends/${encodeURIComponent(backendId!)}/keys`),
    enabled: backendId !== null,
  })
}

export function useCreateKey(backendId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: KeyCreateBody) =>
      apiFetchJson<{ id: string }>(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.keys(backendId) }),
  })
}

export function useDeleteKey(backendId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      apiFetch(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys/${encodeURIComponent(keyId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.keys(backendId) }),
  })
}

// ── Apikeys clients ─────────────────────────────────────────────────────────────

export function useApikeys() {
  return useQuery({
    queryKey: QK.apikeys(),
    queryFn: () => apiFetchJson<MCPApikey[]>('/me/mcp/apikeys'),
  })
}

export function useCreateApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { label: string }) =>
      apiFetchJson<CreatedApikey>('/me/mcp/apikeys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

export function useRevokeApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<{ id: string }>(`/me/mcp/apikeys/${encodeURIComponent(id)}/revoke`, {
        method: 'POST',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

export function useDeleteApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/me/mcp/apikeys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

// ── Grants ────────────────────────────────────────────────────────────────────

export function useGrants(apikeyId: string | null) {
  return useQuery({
    queryKey: QK.grants(apikeyId),
    queryFn: () =>
      apiFetchJson<MCPGrant[]>(`/me/mcp/apikeys/${encodeURIComponent(apikeyId!)}/grants`),
    enabled: apikeyId !== null,
  })
}

export function useSetGrant(apikeyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GrantSetBody) =>
      apiFetchJson<{ apikey_id: string; backend_id: string }>(
        `/me/mcp/apikeys/${encodeURIComponent(apikeyId)}/grants`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.grants(apikeyId) }),
  })
}

export function useDeleteGrant(apikeyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (backendId: string) =>
      apiFetch(
        `/me/mcp/apikeys/${encodeURIComponent(apikeyId)}/grants/${encodeURIComponent(backendId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.grants(apikeyId) }),
  })
}
