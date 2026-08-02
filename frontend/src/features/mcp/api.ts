import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export type Transport = 'streamable_http' | 'sse' | 'stdio' | 'internal'
// Schéma d'auth vers le backend : Bearer (standard MCP) ou header X-API-Key.
export type AuthScheme = 'bearer' | 'x_api_key'
export type StorageType = 'local' | 'harpocrate'

export type BackendHealth = 'up' | 'down' | 'unknown'

export interface MCPBackend {
  id: string
  owner_login: string
  namespace: string
  name: string
  url: string
  transport: Transport
  // Header d'auth utilisé vers le backend (cf. AuthScheme).
  auth_scheme: AuthScheme
  // Propager l'identité humaine (on-behalf-of signé) aux appels sortants.
  forward_identity: boolean
  enabled: boolean
  // URL web optionnelle de l'application (lien « ouvrir » dans la liste). '' = aucun.
  app_url: string
  // Opt-out de la protection anti rug-pull : true = les redéfinitions d'outils
  // ne sont plus quarantinées (backend de confiance). false par défaut.
  quarantine_disabled: boolean
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
  // Non-null = clef générée par le portail pour un workspace (spec 35) :
  // profil non éditable à la main, seule la révocation est permise.
  workspace_ref: string | null
}

export interface MCPProfile {
  id: string
  owner_login: string
  name: string
  description: string
  created_at: string
  updated_at: string | null
  // Profil injecté dans les fichiers de config des agents workspace (spec 35).
  exposed_in_workspaces: boolean
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
  auth_scheme: AuthScheme
  forward_identity: boolean
  app_url: string
}

export interface BackendUpdateBody {
  name: string
  url: string
  transport: Transport
  enabled: boolean
  auth_scheme: AuthScheme
  forward_identity: boolean
  app_url: string
  quarantine_disabled: boolean
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

export interface AgentType {
  id: string
  label: string
}

const QK = {
  backends: () => ['mcp', 'backends'] as const,
  keys: (backendId: string | null) => ['mcp', 'keys', backendId] as const,
  apikeys: () => ['mcp', 'apikeys'] as const,
  profiles: () => ['mcp', 'profiles'] as const,
  profile: (id: string | null) => ['mcp', 'profile', id] as const,
  catalog: (backendId: string | null) => ['mcp', 'catalog', backendId] as const,
  quarantined: (backendId: string) => ['mcp', 'quarantined', backendId] as const,
  agentTypes: () => ['agent-types'] as const,
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
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: QK.backends() })
      // Activer quarantine_disabled lève les quarantaines côté serveur.
      qc.invalidateQueries({ queryKey: QK.quarantined(vars.id) })
      qc.invalidateQueries({ queryKey: QK.catalog(vars.id) })
    },
  })
}

export function useDeleteBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchVoid(`/me/mcp/backends/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

export function useProbeBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<{ id: string; health: BackendHealth }>(
        `/me/mcp/backends/${encodeURIComponent(id)}/probe`,
        { method: 'POST' },
      ),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: QK.backends() })
      // Le probe resynchronise aussi le catalogue (ex. backend internal devpod) —
      // rafraîchit la liste "View tools" affichée si elle est déjà ouverte.
      qc.invalidateQueries({ queryKey: QK.catalog(id) })
      qc.invalidateQueries({ queryKey: QK.quarantined(id) })
    },
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
      apiFetchVoid(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys/${encodeURIComponent(keyId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.keys(backendId) }),
  })
}

export interface KeyProbeResult {
  id: string
  status: 'ok' | 'failed'
  error: string | null
}

/** Teste une clé de service : handshake MCP authentifié avec cette clé précise. */
export function useProbeKey(backendId: string) {
  return useMutation({
    mutationFn: (keyId: string) =>
      apiFetchJson<KeyProbeResult>(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys/${encodeURIComponent(keyId)}/probe`,
        { method: 'POST' },
      ),
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

/** Réponse de rotation : token one-time (clef bearer) OU réinjection (clef workspace). */
export interface RotatedApikey {
  id: string
  token?: string
  workspace?: string
  reinjected?: boolean
}

export function useRotateApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<RotatedApikey>(`/me/mcp/apikeys/${encodeURIComponent(id)}/rotate`, {
        method: 'POST',
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
      apiFetchVoid(`/me/mcp/apikeys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
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

export interface ProfileExposedResult {
  id: string
  exposed: boolean
  affected_workspaces: string[]
  /** Noms des profils décochés par l'exposition (exclusive : un seul à la fois). */
  unexposed_profiles: string[]
}

/**
 * Expose (ou retire) un profil aux workspaces (spec 35). Décocher révoque
 * immédiatement les clefs workspace dérivées du profil (fail closed) et
 * régénère les fichiers de config des agents à chaud.
 */
export function useSetProfileExposed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, exposed }: { id: string; exposed: boolean }) =>
      apiFetchJson<ProfileExposedResult>(
        `/me/mcp/profiles/${encodeURIComponent(id)}/exposed`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ exposed }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.profiles() })
      // La révocation touche les clefs workspace dérivées — la liste des apikeys change.
      qc.invalidateQueries({ queryKey: QK.apikeys() })
    },
  })
}

export function useDeleteProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchVoid(`/me/mcp/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
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
      apiFetchVoid(
        `/me/mcp/profiles/${encodeURIComponent(profileId)}/entries/${encodeURIComponent(backendId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.profile(profileId) }),
  })
}

// ── Types d'agents (spec 35, côté user) ───────────────────────────────────────

/** Types d'agents IA activés (id, label) — alimente le formulaire workspace. */
export function useAgentTypes() {
  return useQuery({
    queryKey: QK.agentTypes(),
    queryFn: () => apiFetchJson<AgentType[]>('/me/agent-types'),
    staleTime: 60_000,
  })
}

// ── Catalog ────────────────────────────────────────────────────────────────────

export type CatalogToolScope = 'read' | 'write' | 'exec' | 'admin' | null

export interface CatalogTool {
  name: string
  description: string
  scope: CatalogToolScope
  quarantined: boolean
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

// ── Quarantaine (anti rug-pull, spec 23) ───────────────────────────────────────

export type PrimitiveKind = 'tool' | 'resource' | 'prompt'

export interface QuarantinedPrimitive {
  kind: PrimitiveKind
  name: string
  description: string
  first_seen: string
  last_seen: string
}

export function useQuarantined(backendId: string) {
  return useQuery({
    queryKey: QK.quarantined(backendId),
    queryFn: () =>
      apiFetchJson<QuarantinedPrimitive[]>(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/quarantined`,
      ),
    // Aligné sur le polling santé : une quarantaine posée par le monitor
    // (~6 min) doit apparaître sans recharger la page.
    refetchInterval: 30_000,
  })
}

export function useApproveQuarantined(backendId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { kind: PrimitiveKind; name: string }) =>
      apiFetchJson<{ id: string }>(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/quarantined/approve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.quarantined(backendId) })
      qc.invalidateQueries({ queryKey: QK.catalog(backendId) })
    },
  })
}

// ── Sources de découverte MCP (étape 2) ────────────────────────────────────

export interface DiscoverySource {
  id: number
  label: string
  slug: string
  url: string
  secret_slug: string
}

export interface DiscoveryProbeResult {
  ok: boolean
  name: string | null
  email: string | null
}

const DISCOVERY_QK = ['mcp', 'discovery-sources'] as const

export function useDiscoverySources() {
  return useQuery({
    queryKey: DISCOVERY_QK,
    queryFn: () => apiFetchJson<DiscoverySource[]>('/me/mcp/discovery-sources'),
  })
}

export function useCreateDiscoverySource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { label: string; slug: string; url: string; secret_slug: string }) =>
      apiFetchJson<DiscoverySource>('/me/mcp/discovery-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: DISCOVERY_QK }),
  })
}

export function useDeleteDiscoverySource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetchVoid(`/me/mcp/discovery-sources/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: DISCOVERY_QK }),
  })
}

/** Teste une source (URL + secret) sans l'enregistrer — valide connectivité + clé. */
export function useProbeDiscoverySource() {
  return useMutation({
    mutationFn: (body: { url: string; secret_slug: string }) =>
      apiFetchJson<DiscoveryProbeResult>('/me/mcp/discovery-sources/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  })
}

// ── Recherche dans une source (étape 3) ─────────────────────────────────────

/** Item de catalogue normalisé (sous-ensemble affiché ; install ajoutée à l'étape 4). */
export interface DiscoveryItem {
  id: number | null
  name: string
  description: string
  transport: string
  category: string | null
  stars: number
  repo_status: string | null
  source_url: string
  doc_url: string
}

export interface DiscoverySearchResult {
  items: DiscoveryItem[]
  total: number
  page: number
  per_page: number
}

/**
 * Recherche dans le catalogue d'une source. Désactivée tant que `sourceId` est
 * nul ou que la requête est vide ; la clé de query inclut page/per_page pour
 * une pagination naturellement mise en cache.
 */
export function useDiscoverySearch(
  sourceId: number | null,
  query: string,
  page: number,
  perPage = 10,
) {
  const q = query.trim()
  return useQuery({
    queryKey: ['mcp', 'discovery-search', sourceId, q, page, perPage] as const,
    queryFn: () => {
      const params = new URLSearchParams({
        q,
        page: String(page),
        per_page: String(perPage),
      })
      return apiFetchJson<DiscoverySearchResult>(
        `/me/mcp/discovery-sources/${sourceId}/search?${params}`,
      )
    },
    enabled: sourceId !== null && q !== '',
  })
}
