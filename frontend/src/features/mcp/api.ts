import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type Transport = 'streamable_http' | 'sse' | 'stdio' | 'internal'
export type StorageType = 'local' | 'harpocrate'

export type BackendHealth = 'up' | 'down' | 'unknown'

export interface MCPBackend {
  id: string
  owner_login: string
  namespace: string
  name: string
  url: string
  transport: Transport
  enabled: boolean
  // URL web optionnelle de l'application (lien « ouvrir » dans la liste). '' = aucun.
  app_url: string
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
  kind: 'apikey' | 'oauth'
  profile_id: string | null
  revoked: boolean
  created_at: string
  last_used_at: string | null
}

export interface MCPProfile {
  id: string
  owner_login: string
  name: string
  description: string
  created_at: string
  updated_at: string | null
}

export interface MCPProfileEntry {
  profile_id: string
  backend_id: string
  backend_key_id: string | null
  tools: string[] | null
}

export interface MCPProfileDetail extends MCPProfile {
  entries: MCPProfileEntry[]
}

export interface ProfileCreateBody {
  name: string
  description?: string
}

export interface EntryUpsertBody {
  backend_key_id?: string | null
  tools: string[] | null
}

export interface BackendCreateBody {
  namespace: string
  name: string
  url: string
  transport: Transport
  app_url: string
}

export interface BackendUpdateBody {
  name: string
  url: string
  transport: Transport
  enabled: boolean
  app_url: string
}

export interface KeyCreateBody {
  slug: string
  description?: string
  storage_type: StorageType
  secret_value: string
  vault_identifier?: string | null
}

export interface CreatedApikey {
  id: string
  token: string
}

const QK = {
  backends: () => ['mcp', 'backends'] as const,
  keys: (backendId: string | null) => ['mcp', 'keys', backendId] as const,
  apikeys: () => ['mcp', 'apikeys'] as const,
  profiles: () => ['mcp', 'profiles'] as const,
  profile: (id: string | null) => ['mcp', 'profile', id] as const,
  catalog: (backendId: string | null) => ['mcp', 'catalog', backendId] as const,
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
    mutationFn: (body: { label: string; profile_id?: string | null }) =>
      apiFetchJson<CreatedApikey>('/me/mcp/apikeys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

export function useSetApikeyProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, profile_id }: { id: string; profile_id: string | null }) =>
      apiFetchJson<{ id: string; profile_id: string | null }>(
        `/me/mcp/apikeys/${encodeURIComponent(id)}/profile`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile_id }),
        },
      ),
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

// ── Profils ────────────────────────────────────────────────────────────────────

export function useProfiles() {
  return useQuery({
    queryKey: QK.profiles(),
    queryFn: () => apiFetchJson<MCPProfile[]>('/me/mcp/profiles'),
  })
}

export function useProfileDetail(profileId: string | null) {
  return useQuery({
    queryKey: QK.profile(profileId),
    queryFn: () =>
      apiFetchJson<MCPProfileDetail>(`/me/mcp/profiles/${encodeURIComponent(profileId!)}`),
    enabled: profileId !== null,
  })
}

export function useCreateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfileCreateBody) =>
      apiFetchJson<{ id: string }>('/me/mcp/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.profiles() }),
  })
}

export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name: string; description: string }) =>
      apiFetchJson<{ id: string }>(`/me/mcp/profiles/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: QK.profiles() })
      qc.invalidateQueries({ queryKey: QK.profile(vars.id) })
    },
  })
}

export function useDeleteProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/me/mcp/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.profiles() }),
  })
}

export function useUpsertEntry(profileId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ backend_id, ...body }: EntryUpsertBody & { backend_id: string }) =>
      apiFetchJson<{ profile_id: string; backend_id: string }>(
        `/me/mcp/profiles/${encodeURIComponent(profileId)}/entries/${encodeURIComponent(backend_id)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.profile(profileId) }),
  })
}

export function useDeleteEntry(profileId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (backendId: string) =>
      apiFetch(
        `/me/mcp/profiles/${encodeURIComponent(profileId)}/entries/${encodeURIComponent(backendId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.profile(profileId) }),
  })
}

// ── Catalog ────────────────────────────────────────────────────────────────────

export interface CatalogTool {
  name: string
  description: string
}

export function useBackendCatalog(backendId: string | null) {
  return useQuery({
    queryKey: QK.catalog(backendId),
    queryFn: () =>
      apiFetchJson<CatalogTool[]>(
        `/me/mcp/backends/${encodeURIComponent(backendId!)}/catalog`,
      ),
    enabled: backendId !== null,
    staleTime: 60_000,
  })
}
